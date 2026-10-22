# -*- coding: utf-8 -*-
"""电竞外部参考：只读公开资料；社区投票、官方赛期和合约报价不混为模型胜率。"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlencode
import layout as L
from reliability import atomic_write_text

__version__='1.0'
URLS={
 'OP.GG':'https://esports.op.gg/worlds/predictions?hl=zh_CN',
 'Ubisoft':'https://www.ubisoft.com/zh-cn/esports/rainbow-six/siege/predictions/502',
 '超凡':'https://www.chaofan.com/match/lol',
 'Polymarket':'https://polymarket.com/zh',
}
DEFAULTS={'启用':True,'OP.GG':True,'Ubisoft':True,'超凡':True,'Polymarket':True,
          '显示同场参考':True,'最低流动性':1000,'最大买卖价差':0.10,'报价最长分钟':30}
SPORTS={'csgo':'cs2','lol':'lol','dota2':'dota2'}
GAME_TAGS={'csgo':{'cs2','counter-strike-2'},'lol':{'lol','league-of-legends'},'dota2':{'dota2','dota-2'}}
ALIASES=[('NAVI','Natus Vincere'),('G2','G2 Esports'),('Fnatic','FNC'),('Gen.G','Gen.G Esports','GEN'),
         ('Bilibili Gaming','BLG'),('Hanwha Life Esports','HLE'),('Top Esports','TES'),('Team Liquid','Liquid','TL'),('T1',)]

def _key(text):return ' '.join(unicodedata.normalize('NFKC',str(text)).casefold().split())
def alias_key(text):
    key=_key(text)
    for group in ALIASES:
        if key in {_key(x) for x in group}:return _key(group[0])
    return key

def stamp(value):
    try:
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            return datetime.fromtimestamp(value,timezone.utc)
        result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if result.tzinfo is None:return None
        return result.astimezone(timezone.utc)
    except (ValueError,TypeError,OverflowError,OSError):return None

def finite(value):
    try:
        if value is None or isinstance(value,bool):return None
        out=float(value);return out if math.isfinite(out) else None
    except (ValueError,TypeError,OverflowError):return None

class _Scripts(HTMLParser):
    def __init__(self):super().__init__();self.on=False;self.data=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.on=dict(attrs).get('id')=='__NEXT_DATA__'
    def handle_endtag(self,tag):
        if tag=='script':self.on=False
    def handle_data(self,data):
        if self.on:self.data.append(data)

def next_data(html):
    p=_Scripts();p.feed(html)
    if not p.data:raise ValueError('公开页面没有可读取的数据状态')
    return json.loads(''.join(p.data))

def opgg_metadata(html,now):
    props=next_data(html).get('props',{}).get('pageProps',{})
    league=next((x for x in props.get('leagues',[]) if isinstance(x,dict) and x.get('shortName')=='Worlds'),None)
    serie=(league or {}).get('latestSerie') or (league or {}).get('recentSerie') or {}
    start,end=stamp(serie.get('beginAt')),stamp(serie.get('endAt'))
    return {'name':'OP.GG','kind':'community_context','game':'lol','state':'metadata_only' if start and end else 'unavailable',
            'url':URLS['OP.GG'],'season':serie.get('year'),'begin':start.isoformat() if start else None,'end':end.isoformat() if end else None,
            'message':'读取到Worlds赛季资料；页面未含可核验的逐场社区票数，本次不采集投票比例。','matched':0}

def ubisoft_metadata(html,now):
    page=next_data(html).get('props',{}).get('pageProps',{}).get('pageData',{})
    competition=page.get('competition') or {};details=(page.get('competitionDetails') or {}).get('competition') or {}
    closes=[stamp(x.get('closeAt')) for x in page.get('phases',[]) if isinstance(x,dict)]
    closes=[x for x in closes if x is not None]
    ended=stamp(details.get('endDate'));locked=bool(closes) and all(x<now for x in closes)
    return {'name':'Ubisoft','kind':'official_context','game':'r6','state':'archived_locked' if locked or (ended and ended<now) else 'context_only',
            'url':URLS['Ubisoft'],'competition_id':competition.get('id'),'competition':competition.get('name'),
            'begin':details.get('startDate'),'end':details.get('endDate'),
            'message':'R6赛事502预测阶段已结束/锁定，不套用到LOL、CS2、DOTA2。' if locked or (ended and ended<now) else '仅R6官方赛事参考，不套用到其他项目。',
            'matched':0}

def chaofan_schedule(data):
    if not isinstance(data,dict) or data.get('code')!=0:raise ValueError('超凡接口未返回成功')
    rows=(data.get('data') or {}).get('list')
    if not isinstance(rows,list):raise ValueError('超凡列表结构变化')
    out=[];pending=list(rows)
    while pending:
        r=pending.pop()
        if not isinstance(r,dict):continue
        if isinstance(r.get('list'),list):pending.extend(r['list'])
        try:
            if int(r.get('game_id',0))!=1:continue
            home,away=r['home']['name'],r['away']['name'];start=float(r['start_time']);bo=int(r['box'])
            if not all(isinstance(v,str) and v for v in (home,away)) or bo not in (1,3,5,7) or not math.isfinite(start):continue
            out.append({'game':'lol','home':home,'away':away,'start':start,'bo':bo,'id':str(r.get('id',''))})
        except (ValueError,TypeError,KeyError,OverflowError):continue
    return out

def match_schedule(pick,rows):
    if pick['game']!='lol':return None
    target={alias_key(pick['home']),alias_key(pick['away'])};kick=stamp(pick['fixture']['start'])
    for r in rows:
        if {alias_key(r['home']),alias_key(r['away'])}!=target:continue
        if abs(r['start']-kick.timestamp())>900:continue
        if r['bo']!=pick['bo']:return {'source':'超凡','kind':'schedule','state':'conflict','url':URLS['超凡'],'message':'超凡同场赛制与主赛程不一致，仅备查。'}
        return {'source':'超凡','kind':'schedule','state':'matched','url':URLS['超凡'],'message':'超凡：同场开赛时间、BO赛制对上；未读取独立胜率。'}
    return None

def _array(value):
    if isinstance(value,str):value=json.loads(value)
    return value if isinstance(value,list) else []

def match_market(pick,event,market,now,cfg):
    """整场二选一合约报价，严格项目/队名/开赛时间；拒绝冠军盘及单图盘。"""
    if not isinstance(event,dict) or not isinstance(market,dict):return None
    if market.get('active') is not True or market.get('closed') is not False:return None
    if market.get('sportsMarketType')!='moneyline' or market.get('line') not in (None,''):return None
    raw_tags=event.get('tags') or []
    if not isinstance(raw_tags,list):return None
    tags={str(t.get('slug','')).casefold() for t in raw_tags if isinstance(t,dict)}
    if not tags&GAME_TAGS.get(pick['game'],set()):return None
    question=str(market.get('question',''))
    if re.search(r'\b(?:map|game)\s*\d+\b|地图\s*\d+|第\s*\d+\s*[局图]|first blood|first tower|total kills|handicap|tournament winner|outright',question,re.I):return None
    bo=re.search(r'\bBO\s*(\d+)\b',question,re.I)
    if bo and int(bo.group(1))!=pick['bo']:return None
    start=stamp(market.get('gameStartTime'));kick=stamp(pick['fixture']['start'])
    if not start or not kick or start<=now or abs((start-kick).total_seconds())>1800:return None
    try:
        outcomes=_array(market.get('outcomes'));prices=_array(market.get('outcomePrices'))
        if len(outcomes)!=2 or len(prices)!=2:return None
        keys=[alias_key(x) for x in outcomes]
        if len(set(keys))!=2 or set(keys)!={alias_key(pick['home']),alias_key(pick['away'])}:return None
        prices=[finite(x) for x in prices]
        if any(x is None or not 0<x<1 for x in prices) or abs(sum(prices)-1)>.05:return None
        home_price=prices[keys.index(alias_key(pick['home']))];away_price=prices[keys.index(alias_key(pick['away']))]
    except (ValueError,TypeError,KeyError,IndexError):return None
    liquidity=finite(market.get('liquidityNum',market.get('liquidity')))
    bid,ask=finite(market.get('bestBid')),finite(market.get('bestAsk'))
    updated=stamp(market.get('updatedAt'));issues=[]
    if liquidity is None or liquidity<cfg['最低流动性']:issues.append('流动性不足/未知')
    if bid is None or ask is None or not 0<=bid<=ask<=1 or ask-bid>cfg['最大买卖价差']:issues.append('买卖价差过大/未知')
    if not updated or not -300<=(now-updated).total_seconds()<=cfg['报价最长分钟']*60:issues.append('报价更新时间过旧/未知')
    direction_price=home_price if alias_key(pick['direction'])==alias_key(pick['home']) else away_price
    return {'source':'Polymarket','kind':'market_quote','state':'quality_limited' if issues else 'matched',
            'url':'https://polymarket.com/event/'+str(event.get('slug') or market.get('slug') or ''),
            'market_id':str(market.get('id','')),'question':question,'home_price':home_price,'away_price':away_price,
            'direction_price':direction_price,'liquidity':liquidity,'spread':ask-bid if bid is not None and ask is not None else None,
            'updated':updated.isoformat() if updated else None,'start':start.isoformat(),'issues':issues,
            'disagreement':not issues and direction_price<.45,
            'message':'Gamma合约报价（可能为中间价或最后成交价），不是模型胜率；仅展示，不参与比分计算。'}

def load_settings(folder,write=True):
    path=L.p(folder,'电竞参考设置.json');cfg=dict(DEFAULTS)
    if path.exists():
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict):raise ValueError('电竞参考设置应为JSON对象')
        cfg.update({k:v for k,v in data.items() if k in cfg})
    elif write:atomic_write_text(path,json.dumps(cfg,ensure_ascii=False,indent=2))
    for key in ('启用','OP.GG','Ubisoft','超凡','Polymarket','显示同场参考'):
        if type(cfg[key]) is not bool:raise ValueError(key+'须为true/false')
    for key,lo,hi in (('最低流动性',0,1e9),('最大买卖价差',.001,.5),('报价最长分钟',1,120)):
        v=finite(cfg[key])
        if v is None or not lo<=v<=hi:raise ValueError(key+'设置无效')
        cfg[key]=v
    return cfg

def collect(folder,picks,now,client, *, write=True,cancel=None,log=None):
    now=now.astimezone(timezone.utc);cancel=cancel or (lambda:False);log=log or (lambda s:None)
    cfg=load_settings(folder,write)
    if not cfg['启用']:return {'enabled':False,'sources':[],'notes':[],'summary':''}
    sources={};jobs=[]
    if cfg['OP.GG']:jobs.append(('OP.GG',URLS['OP.GG']))
    if cfg['Ubisoft']:jobs.append(('Ubisoft',URLS['Ubisoft']))
    if cfg['超凡']:jobs.append(('超凡','https://api-pc.chaofan.com/api/v1/match/list?'+urlencode({'game_id':1,'match_time':int(now.timestamp())})))
    if cfg['Polymarket'] and picks:jobs.append(('Polymarket','https://gamma-api.polymarket.com/sports'))
    cfrows=[];sports=[]
    def read(job):
        name,url=job
        try:return name,client.get(url),''
        except Exception as exc:return name,'',type(exc).__name__
    if cancel():raise RuntimeError('已停止')
    with ThreadPoolExecutor(max_workers=3,thread_name_prefix='esports-ref') as pool:
        for name,body,error in pool.map(read,jobs):
            if cancel():raise RuntimeError('已停止')
            try:
                if error:raise ValueError(error)
                if name=='OP.GG':sources[name]=opgg_metadata(body,now)
                elif name=='Ubisoft':sources[name]=ubisoft_metadata(body,now)
                elif name=='超凡':
                    cfrows=chaofan_schedule(json.loads(body));sources[name]={'name':name,'kind':'schedule','state':'read','url':URLS[name],'rows':len(cfrows),'matched':0,'message':'LOL公开赛程核对，不提供独立预测胜率。'}
                else:
                    sports=json.loads(body)
                    if not isinstance(sports,list):raise ValueError('体育元数据格式变化')
                    sources[name]={'name':name,'kind':'market_quote','state':'read','url':URLS[name],'matched':0,'quality_limited':0,'message':'只比对同场电竞整场胜负市场；合约报价不是模型胜率。'}
            except (ValueError,TypeError,KeyError,AttributeError):
                sources[name]={'name':name,'state':'unavailable','url':URLS[name],'matched':0,'message':'公开数据未读到/结构不符（'+(error or '解析失败')+'），本次不使用，不登录补采。'}
    if cfg['Polymarket'] and not picks:sources['Polymarket']={'name':'Polymarket','state':'no_candidates','url':URLS['Polymarket'],'matched':0,'message':'本次无模型候选，不请求无关市场。'}
    events=[];poly_jobs=[];games={p['game'] for p in picks}
    for game in sorted(games):
        meta=next((s for s in sports if isinstance(s,dict) and s.get('sport')==SPORTS.get(game)),None)
        if not meta or not str(meta.get('series','')).isdigit():continue
        end=max(stamp(p['fixture']['start']) for p in picks if p['game']==game)+timedelta(minutes=30)
        params={'series_id':str(meta['series']),'closed':'false','start_time_min':now.isoformat(),'start_time_max':end.isoformat(),'include_markets':'true','limit':50}
        poly_jobs.append(('Polymarket','https://gamma-api.polymarket.com/events?'+urlencode(params)))
    if poly_jobs:
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix='esports-market') as pool:
            for name,body,error in pool.map(read,poly_jobs):
                if cancel():raise RuntimeError('已停止')
                try:
                    if error:raise ValueError(error)
                    data=json.loads(body)
                    if not isinstance(data,list):raise ValueError('事件结构变化')
                    events.extend(e for e in data if isinstance(e,dict))
                except (ValueError,TypeError):
                    sources['Polymarket']['message']+=' 部分赛事市场读取失败，不沿用旧价格。'
                    sources['Polymarket']['partial_failure']=True
    matches=0
    for p in picks:
        references=[]
        cf=match_schedule(p,cfrows)
        if cf:
            references.append(cf)
            if cf['state']=='matched':sources['超凡']['matched']+=1
        opgg=sources.get('OP.GG',{})
        if p['game']=='lol' and re.search(r'worlds|全球总决赛',p['fixture'].get('event',''),re.I):
            lo,hi=stamp(opgg.get('begin')),stamp(opgg.get('end'));start=stamp(p['fixture']['start'])
            if lo and hi and lo<=start<=hi:
                references.append({'source':'OP.GG','kind':'season_context','state':'context_only','url':URLS['OP.GG'],'message':f'OP.GG：{opgg.get("season")} Worlds赛季日期参考，非逐场票数/胜率。'})
                opgg['matched']+=1
        quotes=[]
        for event in events:
            markets=event.get('markets') or []
            if not isinstance(markets,list):continue
            for market in markets:
                if not isinstance(market,dict):continue
                q=match_market(p,event,market,now,cfg)
                if q:quotes.append(q)
        # 同场选数据质量最高、流动性最大的一个盘口，不把多个盘口当独立共识。
        if quotes:
            best=max(quotes,key=lambda q:(q['state']=='matched',q['liquidity'] or 0))
            references.append(best);key='matched' if best['state']=='matched' else 'quality_limited';sources['Polymarket'][key]+=1
        p['references']=references
        if cfg['显示同场参考']:p['reference_lines']=render_match_refs(p)
        matches+=sum(x['state']=='matched' for x in references)
    for name in URLS:
        if not cfg[name]:sources[name]={'name':name,'state':'disabled','url':URLS[name],'matched':0,'message':'已在设置中关闭。'}
    ordered=[sources[name] for name in URLS if name in sources]
    notes=[f'电竞参考 · {s["name"]}：{s["message"]}（同场/赛期对应 {s.get("matched",0)}）' for s in ordered]
    for note in notes:log('· '+note)
    summary='电竞外部参考\n'+now.isoformat()+'\n\n'+'\n'.join(f'{s["name"]} [{s["state"]}]\n{s["message"]}\n{s["url"]}\n对应：{s.get("matched",0)}\n' for s in ordered)
    return {'enabled':True,'sources':ordered,'notes':notes,'summary':summary,'matched_references':matches,'updated':now.isoformat(),
            'method':'外部来源仅作可核验的上下文、赛程或市场报价展示；不混权计算，不生成社区票数。'}

def render_match_refs(pick):
    lines=[]
    for ref in pick.get('references',[]):
        if ref['source']=='Polymarket' and ref['state']=='matched':
            lines.append(f'参考：Polymarket {pick["direction"]}合约价 {ref["direction_price"]:.2f}（非模型胜率）')
            if ref['disagreement']:lines.append('市场方向与近况模型有分歧。')
        elif ref['source']=='超凡' and ref['state']=='matched':lines.append('参考：超凡赛程时间、BO赛制一致。')
        elif ref['source']=='超凡' and ref['state']=='conflict':lines.append('超凡赛制记录存在分歧，先核对赛程。')
        elif ref['kind']=='season_context':lines.append(ref['message'])
    return lines
