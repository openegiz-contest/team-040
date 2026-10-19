"""Draw an exact schematic from the team's topology; no generated labels or edges."""
from pathlib import Path
import sys, json, math, html
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from team.sim.topology import build_attributes, TOPOLOGY_VERSION
OUT=Path(__file__).resolve().parent
attrs=build_attributes()
nodes=attrs["mine"]["nodes"]
edges={k:v for k,v in attrs.items() if v["kind"]=="working"}
W,H=2400,1850
im=Image.new("RGB",(W,H),"#1c211f")
draw=ImageDraw.Draw(im)
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
fonts={}
def font(size,bold=False,mono=False):
    key=(size,bold,mono)
    if key not in fonts:
        family="consola.ttf" if mono else ("segoeuib.ttf" if bold else "segoeui.ttf")
        fonts[key]=ImageFont.truetype("C:/Windows/Fonts/"+family,size)
    return fonts[key]
def rect(x,y,w,h,fill,stroke=None,r=0):
    draw.rounded_rectangle((x,y,x+w,y+h),radius=r,fill=fill,outline=stroke,width=2)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke or "none"}" stroke-width="2"/>')
def line(points,color,width=2):
    draw.line(points,fill=color,width=width,joint="curve")
    for x,y in (points[0],points[-1]):
        draw.ellipse((x-width/2,y-width/2,x+width/2,y+width/2),fill=color)
    svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>')
def poly(points,fill,stroke=None):
    draw.polygon(points,fill=fill)
    if stroke: draw.line(points+[points[0]],fill=stroke,width=2)
    svg.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in points)}" fill="{fill}" stroke="{stroke or "none"}" stroke-width="2"/>')
def circle(x,y,r,fill,stroke=None):
    draw.ellipse((x-r,y-r,x+r,y+r),fill=fill,outline=stroke,width=2)
    svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke or "none"}" stroke-width="2"/>')
def text(x,y,s,size=24,color="#ebe8dd",bold=False,mono=False,anchor="start"):
    f=font(size,bold,mono)
    tw=draw.textlength(s,font=f)
    px=x if anchor=="start" else x-tw/2 if anchor=="middle" else x-tw
    draw.text((px,y),s,font=f,fill=color,anchor="lt")
    family="Consolas, monospace" if mono else "Segoe UI, Arial, sans-serif"
    svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" font-size="{size}" font-weight="{700 if bold else 400}" text-anchor="{anchor}" dominant-baseline="text-before-edge">{html.escape(s)}</text>')
def tag(x,y,s,color="#ede8db",size=23):
    width=draw.textlength(s,font=font(size,True))+24
    rect(x-width/2,y-7,width,size+20,"#222a27","#59615a",5)
    text(x,y,s,size,color,True,anchor="middle")
def worker(x,y):
    circle(x,y-8,5,"#f4b33c")
    rect(x-5,y-1,10,14,"#e98a3d",r=2)
    line([(x-3,y+12),(x-3,y+19)],"#f2c18e",3)
    line([(x+3,y+12),(x+3,y+19)],"#f2c18e",3)
def sensor(x,y):
    poly([(x,y-9),(x+9,y),(x,y+9),(x-9,y)],"#7ec8c6")
    circle(x,y,3,"#253b3c")
def capsule(x,y,label,color):
    rect(x,y,36,36,color,r=4)
    text(x+18,y+3,label,23,"#202522",True,anchor="middle")

rect(0,0,W,H,"#1c211f")
text(65,45,"РУДНИК / 040",28,"#edb44e",True)
text(65,92,"ПОЛНАЯ СХЕМА ШАХТЫ",48,bold=True)
text(66,154,"Точная связность модели · 2 горизонта · 12 выработок · 2 выхода · 6 работников",24,"#abb8ae")
text(2335,58,"ДЛЯ СБОРКИ СЦЕНЫ",21,"#abb8ae",True,anchor="end")
text(2335,91,"ТОПОЛОГИЯ "+TOPOLOGY_VERSION,25,mono=True,anchor="end")
text(2335,130,"Синтетический объект · 16.10.2026",20,"#abb8ae",anchor="end")
line([(65,204),(2335,204)],"#455049",2)

# Full network. Drawing positions are deliberately schematic; world coordinates in JSON.
pos={"surface-a":(405,300),"surface-b":(1295,300),
     "a":(405,650),"b":(850,650),"c":(1295,650),"d":(850,440),
     "face-a":(850,875),"e":(405,1120),"f":(850,1120),"g":(1295,1120),
     "face-b":(850,1345)}
ramp_bends={"w-01":(165,460),"w-02":(1510,460),
            "w-08":(160,935),"w-09":(1510,935)}
poly([(290,565),(1290,390),(1530,640),(530,820)],"#28332e","#3b4c41")
poly([(290,1040),(1290,970),(1530,1200),(530,1380)],"#28302d","#3b4741")
text(65,553,"ГОРИЗОНТ",18,"#a1b6a8",True)
text(65,584,"−120 м",35,"#ebe8dd",True)
text(65,1024,"ГОРИЗОНТ",18,"#a1b6a8",True)
text(65,1055,"−240 м",35,"#ebe8dd",True)
text(65,253,"ПОВЕРХНОСТЬ / 0 м",23,"#a1b6a8",True)
# Draw all exact edges, no implied crossings or arrows.
drawn=[]
for key,e in edges.items():
    pts=[pos[e["from"]]]
    if key in ramp_bends: pts.append(ramp_bends[key])
    pts.append(pos[e["to"]])
    ramp=e["working_kind"]=="ramp"
    main="#ad956a" if ramp else "#c5cec1"
    line([(x,y+5) for x,y in pts],"#101613",29)
    line(pts,"#616657" if ramp else "#56695b",26)
    line(pts,main,16)
    if e.get("zone"):
        line(pts,"#e9b850",7)
    drawn.append(key)

# Labels placed away from junctions and people.
labels={"w-01":(175,345),"w-02":(1470,345),
        "w-03":(620,675),"w-04":(1080,675),
        "w-05":(570,474),"w-06":(1120,474),
        "w-07":(1030,777),"w-08":(180,955),"w-09":(1470,955),
        "w-10":(620,1145),"w-11":(1080,1145),"w-12":(1030,1245)}
for key,(x,y) in labels.items():
    length=edges[key]["length_m"]
    tag(x,y,f"{key}  /  {length:.1f} м",size=21)

for key,(x,y) in pos.items():
    if key.startswith("surface"):
        circle(x,y,17,"#88b89a","#d2ebd9")
        text(x,y-12,"↑",25,"#1c3427",True,anchor="middle")
        suffix=key[-1].upper()
        text(x+30,y-22,"ВЫХОД "+suffix,25,"#c7e4cf",True)
        text(x+30,y+12,"exit-"+key[-1]+" · "+key,18,"#a6c3af",mono=True)
    elif key.startswith("face"):
        line([(x-15,y),(x+15,y)],"#f0c168",7)
        text(x-27,y+18,key,21,"#f0c168",mono=True)
    else:
        circle(x,y,12,"#202924","#d5dfd1")
        text(x-20,y-43,key,26,"#ffffff",True,mono=True)

for suffix,start,end,level in [("a","b","face-a",-120),("b","f","face-b",-240)]:
    p,q=pos[start],pos[end]
    for i in range(1,4):
        worker(p[0],p[1]+(q[1]-p[1])*i/4)
    sensor(p[0]+29,(p[1]+q[1])/2)
    line([(p[0]+13,(p[1]+q[1])/2),(p[0]+22,(p[1]+q[1])/2)],"#7ec8c6",2)
    text(535,q[1]-28,"УЧАСТОК "+suffix.upper(),25,"#edc477",True)
    text(535,q[1]+7,"zone-"+suffix,20,"#b9c1b4",mono=True)
text(630,365,"ОБХОД ОСНОВНОЙ ВЫРАБОТКИ",18,"#b2c4b6",True)
text(595,403,"a → d → c",21,"#b2c4b6",mono=True)
text(300,1401,"Линии — существующие связи. Стрелки маршрута эвакуации здесь не заданы.",20,"#9daf9f")

# Reference panel: exact lengths and mapping.
rect(1640,240,695,1140,"#e8e4d7",r=12)
text(1675,273,"РЕЕСТР ВЫРАБОТОК",29,"#29372f",True)
text(1675,316,"ID и длины взяты из текущего кода",20,"#5f6b61")
text(1675,369,"ID",20,"#687365",True)
text(1795,369,"СОЕДИНЕНИЕ",20,"#687365",True)
text(2295,369,"ДЛИНА",20,"#687365",True,anchor="end")
for i,(key,e) in enumerate(edges.items()):
    y=412+i*49
    line([(1675,y-12),(2300,y-12)],"#cbcdbf",1)
    text(1675,y,key,22,"#374737",True,mono=True)
    text(1795,y,e["from"]+" — "+e["to"],21,"#374737",mono=True)
    text(2295,y,f'{e["length_m"]:.1f} м',22,"#374737",anchor="end")
line([(1675,1010),(2300,1010)],"#b7bcae",2)
text(1675,1036,"ЧТО ДОЛЖНО СОХРАНИТЬСЯ",23,"#29372f",True)
notes=["Два независимых выхода на поверхность.",
       "Два межгоризонтных съезда: w-08 и w-09.",
       "Обход a — d — c на верхнем горизонте.",
       "Участки А и Б — тупики w-07 и w-12.",
       "Подъёмной клети в расчётной модели нет.",
       "Машины на арт-референсах — декорации."]
for i,s in enumerate(notes): text(1675,1082+39*i,s,21,"#4c5e50")

# Initial positions detail: exact 20/40/60m offsets.
for suffix,x in [("a",65),("b",840)]:
    y=1475
    rect(x,y,735,270,"#29312b","#48564a",10)
    text(x+25,y+22,"УЧАСТОК "+suffix.upper()+" / НАЧАЛЬНОЕ СОСТОЯНИЕ",22,"#ecc16f",True)
    start="b" if suffix=="a" else "f"
    edge="w-07" if suffix=="a" else "w-12"
    base=x+65; last=x+645; yy=y+125
    line([(base,yy),(last,yy)],"#d6c89f",9)
    circle(base,yy,7,"#26352b","#b6c6b5")
    line([(last,yy-12),(last,yy+12)],"#edb44e",5)
    text(base,y+88,start,20,mono=True)
    text(last,y+88,"face-"+suffix,20,mono=True,anchor="end")
    for i in range(1,4):
        px=base+(last-base)*i/4
        worker(px,yy-9)
        text(px,y+156,f"worker-{suffix}{i}",16,"#d5dece",mono=True,anchor="middle")
        text(px,y+180,f"{i*20} м",20,"#edbb78",anchor="middle")
    sensor((base+last)/2,yy-48)
    text((base+last)/2+22,yy-59,"sens-ext-"+suffix+" · 40 м",18,"#93cdcb",mono=True)
    text(x+25,y+225,edge+" · 80 м · отсчёт от узла "+start,19,"#abbfae")
text(1645,1485,"УСЛОВНЫЕ ОБОЗНАЧЕНИЯ",23,"#ccd8c8",True)
line([(1650,1543),(1700,1543)],"#c5cec1",13)
text(1720,1527,"Выработка одного горизонта",21,"#c6d1c0")
line([(1650,1594),(1700,1594)],"#ad956a",13)
text(1720,1578,"Пешеходный съезд",21,"#c6d1c0")
sensor(1668,1644);text(1720,1628,"Датчик деформации",21,"#c6d1c0")
worker(1668,1690);text(1720,1678,"Работник, исходная позиция",21,"#c6d1c0")

line([(65,1780),(2335,1780)],"#455049",2)
text(65,1800,"СХЕМА СВЯЗНОСТИ, НЕ В МАСШТАБЕ · Координаты и изгибы — в topology.json · namespace: team040.mine",20,"#b2c2b3")
svg.append("</svg>")
im.save(OUT/"mine-complete-scheme.png")
(OUT/"mine-complete-scheme.svg").write_text("\n".join(svg),encoding="utf-8")
export={"topology_version":TOPOLOGY_VERSION,"namespace":"team040.mine",
        "source":"team/sim/topology.py","units":"m","synthetic":True,
        "drawing_is_to_scale":False,"nodes":nodes,"workings":{}}
for key,e in edges.items():
    a,b=nodes[e["from"]],nodes[e["to"]]
    points=[[a["x"],a["y"],a["z"]],*e["points"],[b["x"],b["y"],b["z"]]]
    assert abs(sum(math.dist(p,q) for p,q in zip(points,points[1:]))-e["length_m"])<1e-8
    export["workings"][key]={**e,"polyline":points}
for kind in ("worker","sensor","zone","exit"):
    export[kind+"s"]={k:v for k,v in attrs.items() if v["kind"]==kind}
export["drawing_nodes_px"]={k:list(v) for k,v in pos.items()}
assert set(drawn)==set(edges) and len(drawn)==12
assert len(export["workers"])==6 and len(export["sensors"])==2
assert set(pos)==set(nodes)
(OUT/"topology.json").write_text(json.dumps(export,ensure_ascii=False,indent=2),encoding="utf-8")
print("PASS: 12 edges, 11 nodes, 6 workers, 2 sensors, 2 exits; polyline lengths verified.")
