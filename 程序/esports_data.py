# -*- coding: utf-8 -*-
"""电竞赛程/赛果及独立预测；仅读取公开页面数据，不执行网页脚本。"""
from __future__ import annotations
import json
import re

__version__ = '1.3'
_TOKEN=re.compile(r'\s*(?:("(?:\\.|[^"\\])*")|(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|([A-Za-z_$][\w$]*)|([{}\[\](),:;.=]))')

class DataScriptError(ValueError):pass

class _JSData:
    """严格的数据子集解释器；拒绝函数调用、运算、原型属性和其他JS。"""
    def __init__(self,tokens,env=None):self.ts=tokens;self.i=0;self.env=env or {};self.nodes=0
    def pop(self,value=None):
        if self.i>=len(self.ts):raise DataScriptError('数据意外结束')
        token=self.ts[self.i];self.i+=1
        if value is not None and token[1]!=value:raise DataScriptError('数据结构已变化')
        return token
    def peek(self):return self.ts[self.i][1] if self.i<len(self.ts) else None
    def value(self,depth=0):
        self.nodes+=1
        if depth>80 or self.nodes>200000:raise DataScriptError('页面数据过深或过大')
        kind,text=self.pop()
        if kind=='str':return json.loads(text)
        if kind=='num':return float(text) if any(x in text.lower() for x in '.e') else int(text)
        if text=='{':
            out={}
            while self.peek()!='}':
                k,t=self.pop();key=json.loads(t) if k=='str' else t
                if k not in ('str','id','num') or key in ('__proto__','prototype','constructor'):raise DataScriptError('不支持的属性')
                self.pop(':');out[key]=self.value(depth+1)
                if self.peek()!=',':break
                self.pop(',')
            self.pop('}');return out
        if text=='[':
            out=[]
            while self.peek()!=']':
                out.append(self.value(depth+1))
                if self.peek()!=',':break
                self.pop(',')
            self.pop(']');return out
        if kind=='id':
            if text=='new':
                self.pop('Date');self.pop('(');stamp=self.value(depth+1);self.pop(')')
                if not isinstance(stamp,(int,float,str)):raise DataScriptError('日期参数不是字面量')
                return {'$date':stamp}
            if text in ('null','undefined'):return None
            if text in ('true','false'):return text=='true'
            if text in self.env:return self.env[text]
        raise DataScriptError('不是受支持的纯数据表达式')

def _tokens(script):
    pos=0;tokens=[]
    while pos<len(script):
        m=_TOKEN.match(script,pos)
        if not m:
            if not script[pos:].strip():break
            raise DataScriptError('网页脚本不是纯数据格式')
        index=next(i for i,v in enumerate(m.groups()) if v is not None)
        tokens.append((('str','num','id','punc')[index],m.group(index+1)));pos=m.end()
        if len(tokens)>300000:raise DataScriptError('脚本数据过大')
    return tokens

def parse_nuxt(html):
    match=re.search(r'<script[^>]*>\s*window\.__NUXT__\s*=\s*(.*?)</script>',html,re.S|re.I)
    if not match:raise DataScriptError('页面没有可读取的Nuxt公开状态')
    ts=_tokens(match.group(1));p=_JSData(ts);p.pop('(');p.pop('function');p.pop('(');params=[]
    while p.peek()!=')':
        kind,name=p.pop()
        if kind!='id':raise DataScriptError('参数异常')
        params.append(name)
        if p.peek()!=',':break
        p.pop(',')
    p.pop(')');p.pop('{');body_start=p.i;depth=1
    while p.i<len(ts) and depth:
        token=p.pop()
        if token[0]=='punc':
            if token[1]=='{':depth+=1
            elif token[1]=='}':depth-=1
    if depth:raise DataScriptError('数据体不完整')
    body_end=p.i-1;p.pop('(');args=[]
    while p.peek()!=')':
        args.append(p.value())
        if p.peek()!=',':break
        p.pop(',')
    p.pop(')');p.pop(')')
    if p.peek()==';':p.pop(';')
    if p.i!=len(ts) or len(params)!=len(args):raise DataScriptError('不支持的包装表达式')
    env=dict(zip(params,args));b=_JSData(ts[body_start:body_end],env)
    while b.peek() is not None:
        kind,name=b.pop()
        if name=='return':
            result=b.value()
            if b.peek()==';':b.pop(';')
            if b.peek() is not None:raise DataScriptError('return之后有不支持的内容')
            return result
        if kind!='id' or name not in env:raise DataScriptError('非法数据赋值')
        target=env[name];keys=[]
        while b.peek()=='.':
            b.pop('.');k,key=b.pop()
            if k!='id' or key in ('__proto__','prototype','constructor'):raise DataScriptError('非法属性')
            keys.append(key)
        if not keys:raise DataScriptError('不支持替换变量')
        b.pop('=');value=b.value();b.pop(';')
        for key in keys[:-1]:
            if not isinstance(target,dict) or key not in target:raise DataScriptError('非法数据路径')
            target=target[key]
        if not isinstance(target,dict):raise DataScriptError('非法数据对象')
        target[keys[-1]]=value
    raise DataScriptError('缺少公开状态返回值')

def walk_dicts(root):
    pending=[root];seen=set();count=0
    while pending:
        x=pending.pop()
        if not isinstance(x,(dict,list)) or id(x) in seen:continue
        seen.add(id(x));count+=1
        if count>100000:raise DataScriptError('状态内容过大')
        if isinstance(x,dict):yield x;pending.extend(x.values())
        else:pending.extend(x)

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
import time
import unicodedata
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,ProxyHandler,build_opener
import layout as L
from reliability import atomic_write_text

BJT=timezone(timedelta(hours=8))
GAMES={1:'lol',2:'csgo',3:'dota2'}
GAME_LABEL={'csgo':'CS2','lol':'LOL','dota2':'DOTA2'}
DEFAULTS={'启用':True,'项目':['csgo','lol','dota2'],'最多场次':3,'分析候选':24,'超时秒':8,
          '最少地图':6,'最少系列赛':3,'最小单图倾向差':0.06,
          '历史每队页数':3,'历史缓存小时':6,'历史请求上限':24,
          '扩展来源':['CyberScore','GamesOfLegends','OpenDota'],'扩展历史请求上限':12,
          '扩展赛程页数':2,'LOL赛事页数':4,'OpenDota历史页数':2,'CyberScore最大Tier':3}
ALLOWED={'www.esports8.com','app.5eplay.com','esports.op.gg','www.ubisoft.com','www.chaofan.com','api-pc.chaofan.com','gamma-api.polymarket.com',
         'cyberscore.live','gol.gg','api.opendota.com'}


def team_key(name):
    return ' '.join(unicodedata.normalize('NFKC',str(name)).casefold().split())

def match_key(game,name):
    import esports_sources as XS
    return XS.identity(game,name)

def known_team(name):
    if not isinstance(name,str):return False
    text=team_key(name)
    return bool(text and len(text)<80 and not re.search(r'\btbd\b|winner|loser|待定|胜者|败者|未知|\{',text))

def _int(value):
    if isinstance(value,bool):raise ValueError('非整数')
    number=float(value)
    if not math.isfinite(number) or number!=int(number):raise ValueError('非整数')
    return int(number)

def final_series_score(game,bo,a,b):
    """CS2 BO1的13:8属于回合分，转换为1:0；其他整场必须满足先胜局数。"""
    a,b=_int(a),_int(b)
    if min(a,b)<0 or a==b:return None
    if bo==1 and game=='csgo' and max(a,b)>=13 and abs(a-b)>=2:
        return (1,0) if a>b else (0,1)
    needed=bo//2+1
    if bo in (1,3,5,7) and max(a,b)==needed and min(a,b)<needed:return a,b
    return None

def extract_esports8(state, source_url, fetched):
    rows=[]
    for r in walk_dicts(state):
        try:
            if not isinstance(r.get('home'),dict) or not isinstance(r.get('away'),dict):continue
            game=GAMES.get(_int(r['game_id']));status={1:'upcoming',2:'live',3:'finished'}.get(_int(r['status_id']))
            if not game or not status:continue
            home,away=r['home'].get('name',''),r['away'].get('name','')
            bo=_int(r['box']);start=_int(r['start_time'])
            if bo not in (1,3,5,7) or not 946684800<=start<=4102444800:continue
            score=final_series_score(game,bo,r['home'].get('score'),r['away'].get('score')) if status=='finished' else None
            if status=='finished' and score is None:continue
            rows.append({'id':str(r['id']),'game':game,'home':home,'away':away,'start':start,'bo':bo,'status':status,
                         'score':list(score) if score else None,'event':str(r.get('title_full_zh') or r.get('title_full_en') or r.get('title') or ''),
                         'source':'Esports8','url':f'https://www.esports8.com/en/{game}/match/{r["id"]}',
                         'team_ids':{'Esports8':{team_key(home):str(r['home'].get('id') or ''),team_key(away):str(r['away'].get('id') or '')}},
                         'fetched':fetched,'page':source_url})
        except (ValueError,TypeError,KeyError,OverflowError):continue
    return rows

def extract_5e(data,source_url,fetched):
    if not isinstance(data,dict) or data.get('success') is not True:raise ValueError('5E接口未返回成功')
    matches=(data.get('data') or {}).get('matches',[])
    if not isinstance(matches,list):raise ValueError('5E返回结构变化')
    rows=[]
    for r in matches:
        try:
            info,s=r['mc_info'],r['state']
            if info.get('game_type')!='csgo':continue
            bo=_int(info['format']);start=_int(info['plan_ts']);status={0:'upcoming',1:'live',2:'finished'}.get(_int(s['status']))
            if bo not in (1,3,5,7) or not status or not 946684800<=start<=4102444800:continue
            score=final_series_score('csgo',bo,s.get('t1_score'),s.get('t2_score')) if status=='finished' else None
            if status=='finished' and score is None:continue
            rows.append({'id':str(info['id']),'game':'csgo','home':info['t1_info']['disp_name'],'away':info['t2_info']['disp_name'],
                         'start':start,'bo':bo,'status':status,'score':list(score) if score else None,
                         'event':str((r.get('tt_info') or {}).get('disp_name') or ''),'source':'5EPlay',
                         'url':'https://event.5eplay.com/csgo/matches/'+str(info['id']),'page':source_url,'fetched':fetched,
                         'team_ids':{'5EPlay':{team_key(info['t1_info']['disp_name']):str(info['t1_info'].get('id') or ''),
                                               team_key(info['t2_info']['disp_name']):str(info['t2_info'].get('id') or '')}}})
        except (ValueError,TypeError,KeyError,OverflowError):continue
    return rows

def merge_matches(rows):
    """同项目、队名精确对齐且开赛差≤10分钟才合并；状态冲突优先不推荐。"""
    groups=[]
    for r in rows:
        if not isinstance(r,dict) or not all(k in r for k in ('game','home','away','start','bo','status','fetched')):continue
        try:
            if r['game'] not in GAME_LABEL or r['status'] not in ('upcoming','live','finished') or _int(r['bo']) not in (1,3,5,7):continue
            if any(isinstance(r[k],bool) or not isinstance(r[k],(int,float)) or not math.isfinite(r[k]) for k in ('start','fetched')):continue
            if r['status']=='finished' and (not isinstance(r.get('score'),list) or len(r['score'])!=2 or final_series_score(r['game'],r['bo'],*r['score'])!=tuple(r['score'])):continue
        except (ValueError,TypeError,OverflowError):continue
        if not known_team(r['home']) or not known_team(r['away']) or match_key(r['game'],r['home'])==match_key(r['game'],r['away']):continue
        pair=sorted((match_key(r['game'],r['home']),match_key(r['game'],r['away'])))
        found=next((x for x in groups if x['game']==r['game'] and sorted((match_key(x['game'],x['home']),match_key(x['game'],x['away'])))==pair and abs(x['start']-r['start'])<=600),None)
        if found is None:
            n=dict(r);n['team_ids']={k:dict(v) for k,v in r.get('team_ids',{}).items()};n['sources']=[dict(x) for x in r.get('sources',[])] or [{'name':r.get('source',''),'url':r.get('url',''),'fetched':r['fetched']}];n['conflict']=bool(r.get('conflict'));groups.append(n)
        else:
            if r.get('conflict'):found['conflict']=True
            for source, ids in r.get('team_ids',{}).items():
                found.setdefault('team_ids',{}).setdefault(source,{}).update(ids)
            incoming=tuple(r['score']) if r.get('score') else None
            if incoming and match_key(r['game'],r['home'])!=match_key(found['game'],found['home']):incoming=incoming[::-1]
            if r['bo']!=found['bo'] or (incoming and found.get('score') and incoming!=tuple(found['score'])):found['conflict']=True
            if {'upcoming','live'}<=set((r['status'],found['status'])):found['status']='live'
            elif r['status']=='finished':found['status']='finished';found['score']=list(incoming) if incoming else None
            found['fetched']=max(found['fetched'],r['fetched'])
            record={'name':r.get('source',''),'url':r.get('url',''),'fetched':r['fetched']}
            if record not in found['sources']:found['sources'].append(record)
            for record in r.get('sources',[]):
                if record not in found['sources']:found['sources'].append(dict(record))
    return groups

class PublicClient:
    def __init__(self,folder,timeout=8,proxy='',write=True,cancel=None):
        self.folder=Path(folder);self.timeout=timeout;self.write=write;self.cancel=cancel or (lambda:False)
        self.opener=build_opener(ProxyHandler({'http':proxy,'https':proxy}) if proxy else ProxyHandler())
    def get(self,url):
        return self._request(url)
    def post_form(self,url,fields):
        if url!='https://gol.gg/tournament/ajax.trlist.php' or set(fields)!={'season'} or not re.fullmatch(r'S\d{1,2}',str(fields['season'])):
            raise ValueError('非允许的只读赛事目录查询')
        return self._request(url,urlencode(fields).encode('ascii'))
    def _request(self,url,data=None):
        if self.cancel():raise RuntimeError('已停止')
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in ALLOWED or parsed.username or parsed.password:raise ValueError('非公开数据允许的地址')
        with self.opener.open(Request(url,data=data,headers={'User-Agent':'Mozilla/5.0','Referer':f'https://{parsed.hostname}/'}),timeout=self.timeout) as r:
            if urlsplit(r.geturl()).hostname not in ALLOWED:raise ValueError('数据源跳转到其他站点')
            raw=r.read(5*1024*1024+1)
        if len(raw)>5*1024*1024:raise ValueError('页面超过5MiB')
        return raw.decode('utf-8-sig')

def load_settings(folder,write=True):
    path=L.p(folder,'电竞设置.json');cfg=dict(DEFAULTS);data={}
    if path.exists():
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict):raise ValueError('电竞设置应为JSON对象')
        cfg.update({k:v for k,v in data.items() if k in cfg})
    if type(cfg['启用']) is not bool:raise ValueError('电竞启用须为true/false')
    if not isinstance(cfg['项目'],list) or not cfg['项目'] or any(x not in GAME_LABEL for x in cfg['项目']):raise ValueError('电竞项目只支持csgo/lol/dota2')
    if not isinstance(cfg['扩展来源'],list) or any(x not in ('CyberScore','GamesOfLegends','OpenDota') for x in cfg['扩展来源']):raise ValueError('扩展来源只支持CyberScore/GamesOfLegends/OpenDota')
    # 旧版默认仅分析6场，自动迁移；其他自定义值保留。
    if cfg['分析候选']==6:cfg['分析候选']=24
    for k,low,high in (('最多场次',1,4),('分析候选',1,64),('超时秒',2,20),('最少地图',4,30),('最少系列赛',2,10),
                       ('历史每队页数',1,5),('历史缓存小时',1,24),('历史请求上限',2,64),
                       ('扩展历史请求上限',3,30),('扩展赛程页数',1,4),('LOL赛事页数',1,10),('OpenDota历史页数',1,4),('CyberScore最大Tier',1,4)):
        v=_int(cfg[k])
        if not low<=v<=high:raise ValueError(k+'超出范围')
        cfg[k]=v
    edge=float(cfg['最小单图倾向差'])
    if not math.isfinite(edge) or not .02<=edge<=.2:raise ValueError('倾向差须为0.02～0.2')
    cfg['最小单图倾向差']=edge
    if write and any(data.get(k)!=v for k,v in cfg.items()):
        atomic_write_text(path,json.dumps(dict(data,**cfg),ensure_ascii=False,indent=2))
    return cfg

def recent_cs_maps(state,fixture,now):
    """只读分析页逐图记录；明确按回合胜负算地图结果，不把10图误称10场。"""
    analysis=(state.get('state') or {}).get('matchAnalysis') or {}
    recent=analysis.get('recentData') or analysis.get('analysisBaseInfo') or {}
    out={};before=min(now.timestamp(),fixture['start'])
    for side in ('home','away'):
        team=recent.get(side+'_team') or {}
        if match_key(fixture['game'],team.get('name',''))!=match_key(fixture['game'],fixture[side]):continue
        games=[];seen=set()
        for r in team.get('recent',[]):
            try:
                stamp=_int(r['match_time']);stats=r['stats'];a,b=_int(stats[0]),_int(stats[1])
                if _int(r.get('game_id',2))!=2 or not before-90*86400<=stamp<before or str(r.get('match_id'))==fixture.get('id'):continue
                if max(a,b)<13 or abs(a-b)<2:continue  # 不把未完图、击杀统计或13:12当终场
                key=(str(r['match_id']),_int(r['box_num']))
                if key in seen:continue
                seen.add(key);games.append({'at':stamp,'win':int(a>b),'series':key[0],'map':r.get('map_name',''),'score':[a,b]})
            except (ValueError,TypeError,KeyError,IndexError):continue
        out[side]=sorted(games,key=lambda x:x['at'],reverse=True)[:20]
    return out

def history_maps(history,fixture,now,cfg=None):
    cfg=cfg or DEFAULTS
    out={'home':[],'away':[]};before=min(now.timestamp(),fixture['start'])
    for side in out:
        name=match_key(fixture['game'],fixture[side]);pools={}
        for r in history:
            if r.get('game')!=fixture['game'] or r.get('status')!='finished' or r.get('conflict') or not r.get('score'):continue
            if r.get('source') in ('CyberScore','GamesOfLegends','OpenDota') and r['source'] not in cfg['扩展来源']:continue
            if r.get('source')=='CyberScore' and r.get('tier',cfg['CyberScore最大Tier'])>cfg['CyberScore最大Tier']:continue
            if not before-90*86400<=r['start']<before:continue
            if r.get('finished_at',r['start'])>before:continue
            if name not in (match_key(r['game'],r['home']),match_key(r['game'],r['away'])):continue
            score=r['score'] if name==match_key(r['game'],r['home']) else list(reversed(r['score']))
            values=pools.setdefault(r.get('source') or '本地历史',[])
            # 不知道各图顺序，保留完整系列赛，不能在上限处只截取胜图。
            for i in range(sum(score)):
                values.append({'at':r['start'],'win':int(i<score[0]),'series':r.get('id','')+'|'+str(r['start']),
                               'map':'系列赛汇总','score':None,'sources':r.get('sources',[])})
        options=[]
        for values in pools.values():
            ordered=sorted(values,key=lambda x:x['at'],reverse=True)
            kept=[];included=set()
            for v in ordered:
                if v['series'] in included:continue
                group=[x for x in ordered if x['series']==v['series']]
                if len(kept)+len(group)>30:break
                kept.extend(group);included.add(v['series'])
            options.append(kept)
        def quality(values):
            n=len(values);series=len({v['series'] for v in values})
            return (n>=cfg['最少地图'] and series>=cfg['最少系列赛'],n,values[0]['at'] if values else 0)
        # 延期开赛可能令跨站时间相差>10分钟；每队只选一个来源，避免同场重复计数。
        out[side]=max(options,key=quality) if options else []
    return out


def score_distribution(p,bo):
    if bo not in (1,3,5,7) or not math.isfinite(p) or not 0<=p<=1:raise ValueError('赛制或概率无效')
    need=bo//2+1;out=[]
    for lost in range(need):
        out.append((need,lost,math.comb(need+lost-1,lost)*p**need*(1-p)**lost))
        out.append((lost,need,math.comb(need+lost-1,lost)*(1-p)**need*p**lost))
    return sorted(out,key=lambda x:x[2],reverse=True)

def predict(fixture,maps,cfg):
    summary={}
    for side in ('home','away'):
        values=maps.get(side,[])
        n=len(values);series=len({v['series'] for v in values})
        if n<cfg['最少地图'] or series<cfg['最少系列赛']:return None
        wins=sum(v['win'] for v in values)
        summary[side]={'maps':n,'series':series,'wins':wins,'losses':n-wins,'rate':(wins+3)/(n+6)}
    # 简化单图模型：近况向50%收缩，双方图胜率差折半；尚未独立校准。
    p=max(.25,min(.75,.5+.5*(summary['home']['rate']-summary['away']['rate'])))
    if abs(p-.5)<cfg['最小单图倾向差']:return None
    home_favored=p>.5
    dist=score_distribution(p,fixture['bo'])
    scores=[f'{a}:{b}' for a,b,q in dist if (a>b)==home_favored][:2]
    return {'game':fixture['game'],'home':fixture['home'],'away':fixture['away'],'kick':datetime.fromtimestamp(fixture['start'],BJT).strftime('%Y-%m-%d %H:%M'),
            'bo':fixture['bo'],'direction':fixture['home'] if home_favored else fixture['away'],'scores':scores,'form':summary,
            'map_p':p,'edge':abs(p-.5),'sources':fixture.get('sources',[]),'fixture':fixture}

def article(picks,day):
    weekday='周'+'一二三四五六日'[datetime.strptime(day,'%Y-%m-%d').weekday()]
    lines=[f'{day} {weekday}｜电竞预测{len(picks)}场', '北京时间｜系列赛比分参考','']
    for p in picks:
        kick=p['kick'][11:]
        if p['kick'][:10]!=day:kick+='（次日）'
        lines.extend([f'{GAME_LABEL[p["game"]]}｜{p["fixture"]["event"]}｜BO{p["bo"]}｜{kick}',f'{p["home"]} VS {p["away"]}',
                      f'🎯 方向：{p["direction"]}胜',f'🥅 比分参考：'+ ' / '.join(p['scores'])])
        h,a=p['form']['home'],p['form']['away']
        lines.append(f'近况：{p["home"]}近{h["maps"]}图{h["wins"]}胜{h["losses"]}负；{p["away"]}近{a["maps"]}图{a["wins"]}胜{a["losses"]}负。')
        lines.extend(p.get('reference_lines',[]))
        lines.append('')
    if not picks:lines+=['本次没有资料齐全、近况差异足够的未开赛场次，暂不推荐。','']
    lines.append('比分为简化模型参考；未调整阵容、BP、版本和对手强弱。')
    return '\n'.join(lines)

def build(folder,day, *, now=None,proxy='',cancel=None,log=None,write=True,client=None,force_history=False):
    folder=Path(folder);now=now or datetime.now(BJT);now=now.replace(tzinfo=BJT) if now.tzinfo is None else now.astimezone(BJT)
    cfg=load_settings(folder,write);log=log or (lambda s:None);cancel=cancel or (lambda:False)
    if not cfg['启用']:return {'enabled':False,'picks':[],'notes':[],'text':''}
    client=client or PublicClient(folder,cfg['超时秒'],proxy,write,cancel)
    import esports_sources as XS
    notes=[];snapshots=[];source_status=[];fetched=now.timestamp()
    jobs=[('e8',f'https://www.esports8.com/en/{game}') for game in cfg['项目']]
    if 'csgo' in cfg['项目']:
        for page in (1,2):jobs.append(('5e','https://app.5eplay.com/api/tournament/session_list?'+urlencode({'game_status':1,'game_type':1,'grades':'','page':page,'limit':20})))
        jobs.append(('5e','https://app.5eplay.com/api/tournament/session_result_list?'+urlencode({'game_type':1,'order_by':'asc','grades':'','page_size':20,'page_token':''})))
    jobs.extend(XS.fixture_jobs(cfg))
    def fetch(job):
        kind,url=job
        for attempt in range(2):
            if cancel():raise RuntimeError('已停止')
            try:
                body=client.get(url)
                if kind=='e8':data=extract_esports8(parse_nuxt(body),url,fetched)
                elif kind=='cyber':data=XS.extract_cyber(body,url,fetched,cfg['CyberScore最大Tier'])
                else:data=extract_5e(json.loads(body),url,fetched)
                return data,''
            except Exception as exc:
                if cancel():raise RuntimeError('已停止')
                failure=f'HTTP {exc.code}' if getattr(exc,'code',None) else type(exc).__name__
                if getattr(exc,'code',None) in (403,404,429):break
        name={'e8':'Esports8','5e':'5EPlay','cyber':'CyberScore'}[kind]
        return [],f'{name}读取失败（{failure}，已试{attempt+1}次），本次不使用该页。'
    log('电竞：读取Esports8、5EPlay及已启用的扩展赛程…')
    with ThreadPoolExecutor(max_workers=3,thread_name_prefix='esports') as pool:
        for job,(rows,note) in zip(jobs,pool.map(fetch,jobs)):
            if cancel():raise RuntimeError('已停止')
            snapshots.extend(rows)
            source_status.append({'source':{'e8':'Esports8','5e':'5EPlay','cyber':'CyberScore'}[job[0]],'url':job[1],'state':'failed' if note else 'read','rows':len(rows),'message':note})
            if note:notes.append(note)
    path=L.p(folder,'esports_matches.json');old=[]
    try:
        cached=json.loads(path.read_text(encoding='utf-8'));old=cached.get('rows',[]) if isinstance(cached,dict) else []
        old=[r for r in old if isinstance(r,dict) and r.get('status')=='finished' and isinstance(r.get('start'),(int,float)) and now.timestamp()-90*86400<=r['start']<=now.timestamp()]
    except (OSError,ValueError,TypeError):pass
    merged=merge_matches(old+snapshots)
    cutoff=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=BJT)+timedelta(days=1,hours=6)
    current=merge_matches(snapshots)
    candidates=[r for r in current if r['status']=='upcoming' and not r['conflict'] and now.timestamp()+600<r['start']<cutoff.timestamp()]
    candidates.sort(key=lambda r:r['start'])
    import esports_history as EH
    history=EH.HistoryCollector(folder,cfg,now,client,cancel,write,force_history)
    # 同一对阵跨站相差10～30分钟，不能当两场推荐，也不擅自选择开球时间。
    ambiguous=set()
    for i,a in enumerate(candidates):
        for j,b in enumerate(candidates[:i]):
            if a['game']!=b['game'] or a['bo']!=b['bo'] or not 600<abs(a['start']-b['start'])<=1800:continue
            ap={match_key(a['game'],a['home']),match_key(a['game'],a['away'])}
            bp={match_key(b['game'],b['home']),match_key(b['game'],b['away'])}
            if ap==bp and {x['name'] for x in a['sources']}.isdisjoint(x['name'] for x in b['sources']):
                ambiguous.update((i,j))
    pending=[r for i,r in enumerate(candidates) if i not in ambiguous]
    selected=pending[:cfg['分析候选']]
    log(f'电竞：按战队补抓近90天已结束比赛，候选{len(candidates)}场，本轮分析{len(selected)}场…')
    added=history.collect_teams(selected)
    extensions=XS.SourceCollector(folder,cfg,now,client,cancel,write,force_history)
    log('电竞：补抓CyberScore、Games of Legends、OpenDota中已启用的历史来源…')
    extra_series,extra_forms=extensions.collect(selected)
    merged=merge_matches(merged+added+extra_series)
    source_status.extend(extensions.status)
    notes.extend(extensions.notes)
    notes.extend(history.notes)
    notes.append(f'电竞历史：战队历史请求{history.requests}页，缓存复用{history.cache_hits}队，读到{len(added)}条有效终场记录（去重后入库）。')
    picks=[];diagnostics=[]
    for i in sorted(ambiguous):
        f=candidates[i]
        reason='跨站开赛时间相差超过10分钟，疑似同场，暂不重复推荐；等待赛程更新核对'
        diagnostics.append({'game':f['game'],'home':f['home'],'away':f['away'],'start':f['start'],
                            'status':'schedule_conflict','reason':reason})
        log(f'· 电竞 {f["home"]}vs{f["away"]}：'+reason)
    for fixture in selected:
        if cancel():raise RuntimeError('已停止')
        maps=history_maps(merged,fixture,now,cfg)
        # Esports8完整系列赛适用于各项目；CS2另可读明确终场回合的逐图记录。
        e8=next((x for x in fixture['sources'] if x['name']=='Esports8'),None)
        if e8:
            try:
                url=e8['url']+'/analysis';state=parse_nuxt(client.get(url))
                series_rows=EH.analysis_series(state,fixture,now,url)
                merged=merge_matches(merged+series_rows)
                maps=history_maps(merged,fixture,now,cfg)
                if fixture['game']=='csgo':
                    recent=recent_cs_maps(state,fixture,now)
                    # 每一侧独立选完整样本，避免一侧数据不足拖掉另一侧。
                    for side in ('home','away'):
                        v=recent.get(side,[])
                        if len(v)>=cfg['最少地图'] and len({x['series'] for x in v})>=cfg['最少系列赛']:
                            maps[side]=v
                fixture['sources'].append({'name':'Esports8历史分析','url':url,'fetched':now.timestamp()})
            except Exception as exc:
                if cancel():raise RuntimeError('已停止')
                notes.append(f'电竞历史：{fixture["home"]}vs{fixture["away"]} 分析页失败（{type(exc).__name__}），使用本地及备用源已确认赛果。')
        maps,form_sources=XS.supplement_maps(maps,extra_forms,fixture,now,cfg)
        reason=EH.map_shortage(maps,cfg)
        pick=predict(fixture,maps,cfg)
        if pick:
            pick['history_samples']=maps
            pick['form_sources']=form_sources
            picks.append(pick);status='recommended';reason='样本与倾向差达到要求'
        else:
            status='insufficient_history' if reason else 'weak_edge'
            reason=reason or f'近况差异不足：单图倾向差未达到{cfg["最小单图倾向差"]:.0%}'
        diagnostics.append({'game':fixture['game'],'home':fixture['home'],'away':fixture['away'],
                            'start':fixture['start'],'status':status,'reason':reason,'form_sources':form_sources,
                            'samples':{side:{'maps':len(maps[side]),'series':len({v['series'] for v in maps[side]})} for side in ('home','away')}})
        log(f'· 电竞 {fixture["home"]}vs{fixture["away"]}：'+('生成推荐' if pick else reason))
    # 候选先全部分析再按倾向差排序，避免前几场占满名额后遗漏更充分的样本。
    picks.sort(key=lambda p:(-p['edge'],p['fixture']['start']))
    excluded=picks[cfg['最多场次']:];picks=picks[:cfg['最多场次']]
    for d in diagnostics:
        if any(d['game']==p['game'] and d['home']==p['home'] and d['away']==p['away'] and d['start']==p['fixture']['start'] for p in excluded):
            d.update(status='selection_limit',reason='符合条件，受最多场次限制未入选')
    for fixture in pending[len(selected):]:
        diagnostics.append({'game':fixture['game'],'home':fixture['home'],'away':fixture['away'],
                            'start':fixture['start'],'status':'analysis_limit','reason':'受分析候选上限限制，本轮未分析'})
    # 只保存规范化赛程与已确认比分，不保存页面脚本或站点配置字段。
    if write:
        try:
            atomic_write_text(path,json.dumps({'rows':merged,'updated_bjt':now.isoformat()},ensure_ascii=False))
            history.save()
        except OSError:notes.append('电竞赛果库未保存，检查文件占用或目录权限。')
    extensions.save()
    for note in extensions.notes:
        if note not in notes:notes.append(note)
    for note in history.notes:
        if note not in notes:notes.append(note)
    counts={key:sum(d['status']==key for d in diagnostics) for key in ('recommended','insufficient_history','weak_edge','analysis_limit','selection_limit','schedule_conflict')}
    notes += [f'电竞：读到{len(current)}场，时间候选{len(candidates)}场；推荐{counts["recommended"]}场，历史不足{counts["insufficient_history"]}场，差异不足{counts["weak_edge"]}场，分析上限未分析{counts["analysis_limit"]}场，推荐名额未入选{counts["selection_limit"]}场，跨站时间冲突{counts["schedule_conflict"]}条。',
              '电竞预测未做独立回测和校准；不进入足球/篮球历史命中率，模型不使用赔率或合约报价计算，不把图数当系列赛场数。']
    for note in dict.fromkeys(notes):log('· '+note)
    references = None
    try:
        import esports_refs as ER
        log('电竞：核对OP.GG、Ubisoft、超凡和Polymarket外部参考…')
        references = ER.collect(folder,picks,now,client,write=write,cancel=cancel,log=log)
        notes.extend(references.get('notes',[]))
    except Exception as exc:
        if cancel():raise RuntimeError('已停止')
        notes.append('电竞外部参考未完成（'+type(exc).__name__+'），没有补写任何外部胜率，保留原近况模型结果。')
        log('· '+notes[-1])
    return {'enabled':True,'picks':picks,'diagnostics':diagnostics,'counts':counts,'source_status':source_status,'references':references,'notes':list(dict.fromkeys(notes)),'text':article(picks,day),'day':day,
            'updated_bjt':now.isoformat(),'model':'收缩后的近期图胜率差、独立同分布单图假设；仅作比分参考，未回测校准'}


def diagnostics_text(result):
    lines=[f'{result.get("day", "")} 电竞逐场诊断（北京时间）','']
    for d in result.get('diagnostics',[]):
        kick=datetime.fromtimestamp(d['start'],BJT).strftime('%m-%d %H:%M')
        lines.append(f'{GAME_LABEL[d["game"]]} {kick} {d["home"]} VS {d["away"]}：{d["reason"]}')
    if not result.get('diagnostics'):lines.append('没有符合开赛时间条件的候选；请查看下方来源状态。')
    lines.extend(['','来源与历史补抓状态：']+result.get('notes',[]))
    return '\n'.join(lines)


def main(argv=None):
    ap=argparse.ArgumentParser(description='电竞预测：公开多源赛程与历史战绩，单篇比分参考')
    ap.add_argument('--refresh-history',action='store_true',help='本次强制刷新候选战队历史，忽略检查时间缓存')
    ap.add_argument('--date',default=datetime.now(BJT).strftime('%Y-%m-%d'));ap.add_argument('--proxy',default='')
    args=ap.parse_args(argv)
    try:
        day=datetime.strptime(args.date,'%Y-%m-%d').strftime('%Y-%m-%d');root=L.app_root(__file__)
        result=build(root,day,proxy=args.proxy,log=print,force_history=args.refresh_history)
        if not result['enabled']:print('电竞预测已在设置中关闭');return 0
        dest=L.p(root,f'电竞推单_{day}.txt');atomic_write_text(dest,result['text'])
        report=L.d(root,L.REP)/f'电竞预测来源_{day}.json';atomic_write_text(report,json.dumps(result,ensure_ascii=False,indent=1))
        atomic_write_text(L.d(root,L.REP)/f'电竞逐场诊断_{day}.txt',diagnostics_text(result))
        refs=result.get('references') or {}
        if refs.get('enabled'):
            atomic_write_text(L.d(root,L.REP)/f'电竞参考报告_{day}.txt',refs['summary'])
        print('已保存：',dest);return 0 if result['picks'] else 2
    except Exception as exc:print('电竞预测未完成：'+type(exc).__name__+'：'+str(exc));return 1

if __name__=='__main__':raise SystemExit(main())
