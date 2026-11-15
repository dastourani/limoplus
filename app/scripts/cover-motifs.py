"""
Source of the extra cover motifs (app/src/lib/coverExtra.ts) and their Django choices.

    python3 scripts/cover-motifs.py src/lib/coverExtra.ts /tmp/choices.txt

Then paste the choices into ContentNode.Motif (backend/apps/catalog/models.py), run makemigrations, and
`npm run build:admin-preview`. See docs/covers.md.
"""
import math, random, sys
# Each motif is a list of SVG element strings using ${L} (main line), ${S} (soft), ${B} (cover background) placeholders.
def path(d, c='L', w=2.6, extra=''): return f'<path d="{d}" stroke="${{{c}}}" stroke-width="{w}"{extra}/>'
def poly(pts, c='L', w=2.6, extra=''): return f'<polyline points="{pts}" stroke="${{{c}}}" stroke-width="{w}"{extra}/>'
def circ(x,y,r,c='L',w=2.4,fill=None):
    f=f' fill="${{{fill}}}"' if fill else ''
    return f'<circle cx="{x}" cy="{y}" r="{r}" stroke="${{{c}}}" stroke-width="{w}"{f}/>'
def dot(x,y,r=3,c='L'): return f'<circle cx="{x}" cy="{y}" r="{r}" fill="${{{c}}}" stroke="none"/>'
def rect(x,y,w,h,c='L',sw=2.4,rx=4,fill=None):
    f=f' fill="${{{fill}}}"' if fill else ''
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" stroke="${{{c}}}" stroke-width="{sw}"{f}/>'
def text(x,y,t,c='S',size=11,anchor='middle',italic=True):
    st=' font-style="italic"' if italic else ''
    return f'<text x="{x}" y="{y}" fill="${{{c}}}" stroke="none" font-size="{size}" text-anchor="{anchor}" font-family="Georgia, serif"{st}>{t}</text>'
def arrow(x1,y1,x2,y2,c='L',w=2.4,head=7):
    a=math.atan2(y2-y1,x2-x1)
    hx1=x2-head*math.cos(a-0.45); hy1=y2-head*math.sin(a-0.45)
    hx2=x2-head*math.cos(a+0.45); hy2=y2-head*math.sin(a+0.45)
    return path(f'M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f} M{hx1:.1f},{hy1:.1f} L{x2:.1f},{y2:.1f} L{hx2:.1f},{hy2:.1f}',c,w)
def pts(xs,f): return ' '.join(f'{x:.1f},{f(x):.1f}' for x in xs)
DASH=' stroke-dasharray="4 5"'
M={}
AX=path('M14,124 L190,124 M20,130 L20,12','S',1.4)

# --- Math
f=lambda x: 112-75*math.exp(-((x-105)/45)**2)
rects=' '.join(f'M{x0},124 L{x0},{f(x0+10):.1f} L{x0+20},{f(x0+10):.1f} L{x0+20},124' for x0 in range(40,160,20))
x=72; d=f(x+0.5)-f(x-0.5); y=f(x)
M['calculus']=[AX, path(rects,'S',1.4), poly(pts(range(20,191,5),f)), path(f'M{x-40},{y-40*d:.1f} L{x+40},{y+40*d:.1f}','L',2), dot(x,round(y,1),3.5)]

def P(u,v):
    h=math.exp(-(u*u+v*v)*1.6); return 100+(u-v)*58, 80+(u+v)*24-50*h
el=[]
for i in range(9):
    u=-1+2*i/8
    el.append(poly(' '.join('%.1f,%.1f'%P(u,-1+2*j/20) for j in range(21)),'L',1.6))
    el.append(poly(' '.join('%.1f,%.1f'%P(-1+2*j/20,u) for j in range(21)),'S',1.2))
M['surface']=el

mx=lambda t:16+t*28; my=lambda y:124-(y+0.2)*(108/1.6)
segs=[]
for i in range(7):
    for j in range(6):
        t=0.3+i*0.9; yv=-0.1+j*0.28; s=yv*(1-yv)
        vx,vy=28,-(108/1.6)*s; L=math.hypot(vx,vy); vx,vy=vx/L*7,vy/L*7; X,Y=mx(t),my(yv)
        segs.append(f'M{X-vx:.1f},{Y-vy:.1f} L{X+vx:.1f},{Y+vy:.1f}')
def logi(y0): return ' '.join(f'{mx(k*0.1):.1f},{my(1/(1+(1/y0-1)*math.exp(-k*0.14))):.1f}' for k in range(61))
M['slopefield']=[path(' '.join(segs),'S',1.5), poly(logi(0.04),'L',2.6), poly(logi(0.3),'L',1.6,DASH)]

O=(52,108)
M['vectors']=[path('M14,108 L190,108 M52,130 L52,10','S',1.2), arrow(52,108,150,88,'L',2.6), arrow(52,108,92,36,'L',2.6),
    path('M150,88 L190,16 M92,36 L190,16','S',1.4,DASH), arrow(52,108,186,18,'S',1.6), text(152,104,'a','L',13), text(80,34,'b','L',13), text(176,40,'a+b','S',11)]

X=lambda x:16+x*42; Y=lambda y:104-y*6.0
curve=' '.join(f'{X(x/20):.1f},{Y((x/20)**2-2):.1f}' for x in range(0,81) if Y((x/20)**2-2)>6)
el=[path(f'M14,{Y(0)} L190,{Y(0)}','S',1.4), poly(curve,'L',2.6)]
x0=3.4
for k in range(3):
    fx=x0*x0-2; x1=x0-fx/(2*x0)
    el.append(path(f'M{X(x0):.1f},{Y(fx):.1f} L{X(x1):.1f},{Y(0):.1f}','S',1.5))
    el.append(path(f'M{X(x1):.1f},{Y(0):.1f} L{X(x1):.1f},{Y(x1*x1-2):.1f}','S',1.2,' stroke-dasharray="2 4"'))
    el.append(dot(round(X(x0),1),round(Y(fx),1),3))
    x0=x1
el.append(dot(round(X(math.sqrt(2)),1),Y(0),4))
M['newton']=el

el=[]
for r,c,w in ((14,'L',2.4),(28,'L',1.8),(44,'S',1.5),(60,'S',1.3)):
    el.append(f'<ellipse cx="128" cy="62" rx="{r*1.5:.0f}" ry="{r*0.8:.0f}" transform="rotate(-18 128 62)" stroke="${{{c}}}" stroke-width="{w}"/>')
el.append(poly('22,126 48,104 40,86 72,78 70,62 98,62 104,54 124,60','L',2.4))
el+= [dot(22,126,3), dot(72,78,3), dot(98,62,3), dot(128,62,4)]
M['contour']=el

M['simplex']=[AX, path('M20,40 L120,134 M20,70 L190,30 M150,10 L176,130','S',1.2,' stroke-dasharray="3 5"'),
    '<path d="M20,124 L20,64 L84,49 L150,38 L170,124 Z" stroke="${L}" stroke-width="2.6"/>',
    path('M100,22 L200,46','S',1.4,DASH), arrow(110,100,136,74,'L',2.2), dot(150,38,4.5)]

nodes=[(30,40),(30,100),(80,20),(84,72),(84,122),(136,46),(138,104),(184,72)]
edges=[(0,2),(0,3),(1,3),(1,4),(2,5),(3,5),(3,6),(4,6),(5,7),(6,7),(2,3)]
hot=[(0,3),(3,5),(5,7)]
el=[path(' '.join(f'M{nodes[a][0]},{nodes[a][1]} L{nodes[b][0]},{nodes[b][1]}' for a,b in edges if (a,b) not in hot),'S',1.5),
    path(' '.join(f'M{nodes[a][0]},{nodes[a][1]} L{nodes[b][0]},{nodes[b][1]}' for a,b in hot),'L',2.6)]
el+=[circ(x,y,7,'L',2.2,'B') for x,y in nodes]
M['graph']=el

M['complex']=[path('M14,76 L190,76 M70,130 L70,10','S',1.3), circ(70,76,42,'S',1.3), arrow(70,76,150,30,'L',2.6), path('M70,76 L150,122','S',1.6,DASH),
    path('M150,30 L150,122','S',1,' stroke-dasharray="2 4"'), dot(150,30,4), dot(150,122,3.5,'S'),
    text(162,28,'z','L',15), text(162,128,'z','S',15), path('M157,112 L167,112','S',1.4), text(184,72,'Re','S',10), text(82,16,'Im','S',10)]

# --- Statistics
g=lambda x:120-95*math.exp(-((x-105)/26)**2/2)
M['bell']=[path('M14,120 L190,120','S',1.4), path(' '.join(f'M{x},120 L{x},{g(x):.1f}' for x in range(140,190,6)),'S',1.4),
    poly(pts(range(14,197,4),g),'L',2.6), path('M105,124 L105,20','S',1.2,DASH), path('M79,118 L79,124 M131,118 L131,124','L',2), text(105,136,'μ','S',11)]

M['survival']=[AX, poly('20,22 46,22 46,34 70,34 70,46 96,46 96,52 124,52 124,64 150,64 150,70 186,70','L',2.6),
    poly('20,22 38,22 38,40 58,40 58,62 80,62 80,80 104,80 104,96 136,96 136,104 186,104','S',1.8),
    path('M60,30 L60,38 M110,48 L110,56 M170,66 L170,74','L',1.6), path('M90,76 L90,84 M160,100 L160,108','S',1.4)]

random.seed(4)
P2=[(24+i*10.5, 112-0.48*(24+i*10.5-20)+random.uniform(-14,14)) for i in range(16)]
el=[AX, path(' '.join(f'M{x:.1f},{y:.1f} L{x:.1f},{112-0.48*(x-20):.1f}' for x,y in P2[::3]),'S',1,' stroke-dasharray="2 3"'),
    path('M20,112 L190,30.4','L',2.6)]
el+=[circ(round(x,1),round(y,1),3.4,'S',1.6) for x,y in P2]
M['regression']=el

# --- Physics and chemistry
traj=lambda x:120-0.0150*(x-20)*(180-x)
M['projectile']=[path('M14,122 L190,122','S',1.4), poly(pts(range(20,181,5),traj),'L',2.6,' stroke-dasharray="1 0"'),
    arrow(20,120,38,77,'S',1.8), arrow(100,traj(100),130,traj(100),'S',1.8), arrow(100,traj(100),100,traj(100)+22,'S',1.8),
    path('M34,122 A14,14 0 0 0 28,110','L',1.6), dot(100,round(traj(100),1),4)]

el=[]
for ang,c,w in ((0,'L',2.4),(60,'S',1.6),(120,'S',1.6)):
    el.append(f'<ellipse cx="100" cy="70" rx="78" ry="24" transform="rotate({ang} 100 70)" stroke="${{{c}}}" stroke-width="{w}"/>')
el+=[circ(96,68,6,'L',2,'L'), circ(105,72,6,'L',2,'B'), circ(100,63,5,'L',2,'L'), dot(178,70,4), dot(61,36,3.5,'S'), dot(61,104,3.5,'S')]
M['atom']=el

hx=[(70+32*math.cos(math.radians(30+60*i)), 72+32*math.sin(math.radians(30+60*i))) for i in range(6)]
hexp='M'+' L'.join(f'{x:.1f},{y:.1f}' for x,y in hx)+' Z'
top=hx[4]; right=hx[0]
M['molecule']=[path(hexp,'L',2.6), circ(70,72,20,'S',1.6),
    path(f'M{right[0]:.1f},{right[1]:.1f} L126,56 L152,72 L178,56','L',2.4), path('M152,72 L152,100','L',2.4), path('M156,72 L156,98','S',1.4),
    path(f'M{top[0]:.1f},{top[1]:.1f} L{top[0]:.1f},16','L',2.4), text(152,114,'O','L',13,italic=False), text(184,52,'OH','S',11,italic=False), text(top[0],12,'NH₂','S',10,italic=False)]

a=lambda x:70+30*math.sin((x-14)/22)
b=lambda x:70-30*math.sin((x-14)/22)
M['dna']=[path(' '.join(f'M{x},{a(x):.1f} L{x},{b(x):.1f}' for x in range(20,190,11)),'S',1.4), poly(pts(range(14,191,3),a),'L',2.6), poly(pts(range(14,191,3),b),'S',2.2)]

# --- Body and medicine
def beat(x):
    return f'L{x+8},84 Q{x+14},76 {x+20},84 L{x+26},84 L{x+29},90 L{x+33},24 L{x+37},98 L{x+41},84 L{x+50},84 Q{x+60},70 {x+70},84 L{x+80},84'
M['ecg']=[path('M10,84 L190,84','S',1,' stroke-dasharray="2 5"'), path('M10,84 '+beat(10)+' '+beat(90)+' L190,84','L',2.6), dot(43,24,3.5)]

M['heart']=[path('M100,44 C82,20 40,24 42,62 C44,92 80,110 100,130 C120,110 156,92 158,62 C160,24 118,20 100,44 Z','L',2.6),
    path('M106,40 C104,12 140,6 152,24 M120,14 L120,2 M134,10 L138,0 M88,36 C84,22 70,16 62,22','L',2.4),
    path('M100,52 C94,74 96,98 100,122 M60,64 C74,58 86,60 96,68','S',1.5)]

M['feedback']=[circ(36,64,11,'L',2.4), text(28,52,'+','S',11,italic=False), text(28,86,'−','S',12,italic=False), arrow(6,64,24,64,'S',1.8),
    arrow(47,64,66,64), rect(66,48,40,32,'L',2.6,6), text(86,69,'C','L',14), arrow(106,64,124,64), rect(124,48,40,32,'L',2.6,6), text(144,69,'G','L',14),
    path('M164,64 L194,64','L',2.4), path('M180,64 L180,112 L36,112 L36,76','S',1.8), path('M31,82 L36,75 L41,82','S',1.8)]

M['circuit']=[path('M30,40 L30,58 M30,82 L30,110 L66,110 M90,110 L170,110 L170,92 M170,52 L170,40 L136,40 M64,40 L30,40','L',2.4),
    path('M20,58 L40,58 M24,66 L36,66 M20,74 L40,74 M24,82 L36,82','L',2.4),
    path('M64,40 L70,30 L80,50 L90,30 L100,50 L110,30 L120,50 L130,30 L136,40','L',2.4),
    path('M170,52 C182,52 182,62 170,62 C182,62 182,72 170,72 C182,72 182,82 170,82 C182,82 182,92 170,92','L',2.4),
    path('M66,98 L66,122 M90,98 L90,122','L',2.6), text(100,26,'R','S',11), text(192,76,'L','S',11), text(78,136,'C','S',11)]

M['mri']=[arrow(28,128,28,14,'S',1.8), text(44,24,'B₀','S',12), f'<ellipse cx="124" cy="38" rx="34" ry="10" stroke="${{S}}" stroke-width="1.4" stroke-dasharray="3 4"/>',
    arrow(110,118,152,36,'L',2.8,9), dot(110,118,4), path('M88,44 A34,10 0 0 0 108,48','L',1.8), path('M100,47 L108,48 L102,42','L',1.8),
    poly(' '.join(f'{x},{126-8*math.sin((x-130)/4)*math.exp(-(x-130)/40):.1f}' for x in range(130,194,2)),'S',1.6)]

el=[rect(12,44,22,52,'L',2.6,5), path('M34,52 L40,52 L40,88 L34,88','L',2)]
for r in (26,46,66):
    el.append(path(f'M{36+r*0.55:.1f},{70-r*0.83:.1f} A{r},{r} 0 0 1 {36+r*0.55:.1f},{70+r*0.83:.1f}','S',1.5))
el.append('<ellipse cx="150" cy="70" rx="18" ry="26" stroke="${L}" stroke-width="2.6"/>')
for r in (14,24):
    el.append(path(f'M{132-r*0.5:.1f},{70-r*0.85:.1f} A{r},{r} 0 0 0 {132-r*0.5:.1f},{70+r*0.85:.1f}','L',1.8,DASH))
M['ultrasound']=el

M['biomech']=[path('M58,14 L68,86','S',3.2), path('M68,86 L168,66','L',3.2), circ(68,86,5,'L',2.4,'B'), circ(176,86,10,'L',2.4),
    path('M168,66 L176,76','L',2), arrow(176,98,176,128,'L',2.2), text(190,122,'W','S',11),
    path('M60,22 C88,40 96,64 92,82','S',2), arrow(92,84,94,58,'S',1.6), text(108,60,'F','S',11), path('M58,14 L48,10','S',3)]

layers=[[34,70,106],[86,58,82,106,34],[140,52,88],[180,70]]
xs=[24,74,128,180]
lay=[[(xs[0],34),(xs[0],70),(xs[0],106)],[(xs[1],y) for y in (24,54,84,114)],[(xs[2],y) for y in (40,76,112)],[(xs[3],70)]]
edges=[]
for L1,L2 in zip(lay,lay[1:]):
    for p1 in L1:
        for p2 in L2: edges.append((p1,p2))
hotp=[(lay[0][1],lay[1][1]),(lay[1][1],lay[2][1]),(lay[2][1],lay[3][0])]
el=[path(' '.join(f'M{a[0]},{a[1]} L{b[0]},{b[1]}' for a,b in edges if (a,b) not in hotp),'S',1),
    path(' '.join(f'M{a[0]},{a[1]} L{b[0]},{b[1]}' for a,b in hotp),'L',2.4)]
el+=[circ(x,y,7,'L',2.2,'B') for L in lay for x,y in L]
M['network']=el

M['microscope']=[path('M52,126 L148,126','L',2.8), path('M76,126 C76,112 86,108 100,108 L120,108','S',2), path('M120,108 L120,92 L74,92','L',2.6),
    path('M128,96 C150,80 150,44 122,30','L',2.8), rect(96,16,20,44,'L',2.6,3), path('M100,60 L112,60 L110,72 L102,72 Z','L',2.2),
    path('M92,12 L120,12','L',2.8), circ(150,62,7,'S',1.6), path('M74,92 L74,100 M62,100 L128,100','S',1.8), circ(106,100,3,'L',1.6,'L')]

el=[circ(70,66,24,'L',2.6)]
for i in range(10):
    t=math.radians(i*36); x1=70+24*math.cos(t); y1=66+24*math.sin(t); x2=70+34*math.cos(t); y2=66+34*math.sin(t)
    el.append(path(f'M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}','L',2.2)); el.append(dot(round(x2,1),round(y2,1),3.2))
el+=[path('M60,58 C66,52 76,54 78,62 M62,74 C70,80 78,76 80,70','S',1.5),
     path('M150,124 L150,92 L130,66 M150,92 L170,66','S',2.6), path('M136,60 L124,72 M164,60 L176,72','S',2.6),
     f'<rect x="132" y="12" width="52" height="22" rx="11" stroke="${{S}}" stroke-width="1.6"/>', path('M184,23 L194,18 M184,23 L194,28','S',1.4)]
M['microbe']=el

s=lambda x,c:118-92/(1+math.exp(-(x-c)/14))
M['dose']=[AX, poly(pts(range(20,191,4),lambda x:s(x,85)),'L',2.6), poly(pts(range(20,191,4),lambda x:s(x,128)),'S',1.8,DASH),
    path('M20,72 L85,72 L85,124','S',1.1,' stroke-dasharray="2 4"'), dot(85,72,3.5), text(85,136,'EC50','S',9,italic=False)]

# --- Computing and general
M['code']=[path('M50,24 C36,24 40,46 40,58 C40,66 34,70 28,70 C34,70 40,74 40,82 C40,94 36,116 50,116','L',2.8),
    path('M150,24 C164,24 160,46 160,58 C160,66 166,70 172,70 C166,70 160,74 160,82 C160,94 164,116 150,116','L',2.8),
    path('M64,46 L118,46 M74,62 L136,62 M74,78 L110,78 M64,94 L98,94','S',2.6), path('M120,72 L120,86','L',2.4)]

M['book']=[path('M100,30 C80,18 44,18 22,26 L22,114 C44,106 80,106 100,118 C120,106 156,106 178,114 L178,26 C156,18 120,18 100,30 Z','L',2.6),
    path('M100,30 L100,118','L',2), path('M34,42 C52,37 72,37 88,44 M34,58 C52,53 72,53 88,60 M34,74 C52,69 72,69 88,76 M112,44 C128,37 148,37 166,42 M112,60 C128,53 148,53 166,58 M112,76 C128,69 148,69 166,74','S',1.5)]

LABELS={
 'calculus':('مشتق و انتگرال','ریاضی عمومی ۱، حسابان'),
 'surface':('رویه‌ی سه‌بعدی','ریاضی عمومی ۲، توابع چندمتغیره'),
 'slopefield':('میدان شیب','معادلات دیفرانسیل'),
 'vectors':('بردارها','جبر خطی، مکانیک'),
 'newton':('روش نیوتن','محاسبات عددی، آنالیز عددی'),
 'contour':('منحنی‌های تراز و کمینه','بهینه‌سازی'),
 'simplex':('ناحیه‌ی شدنی','تحقیق در عملیات، برنامه‌ریزی خطی'),
 'graph':('گراف','ریاضیات گسسته، ساختمان داده، الگوریتم'),
 'complex':('صفحه‌ی مختلط','متغیرهای مختلط'),
 'bell':('منحنی زنگوله‌ای','آمار و احتمال'),
 'survival':('منحنی بقا','آمار حیاتی، اپیدمیولوژی'),
 'regression':('رگرسیون','آمار، روش تحقیق، اقتصادسنجی'),
 'projectile':('پرتابه','فیزیک ۱، مکانیک'),
 'atom':('اتم','فیزیک، فیزیک پزشکی، فیزیک هسته‌ای'),
 'molecule':('مولکول','شیمی عمومی و آلی'),
 'dna':('مارپیچ DNA','بیوشیمی، ژنتیک، زیست مولکولی'),
 'ecg':('نوار قلب','فیزیولوژی، سیگنال‌های حیاتی'),
 'heart':('قلب','آناتومی، قلب و عروق'),
 'feedback':('حلقه‌ی بازخورد','کنترل خطی، سیستم‌های کنترل'),
 'circuit':('مدار RLC','مدار الکتریکی، الکترونیک'),
 'mri':('اسپین و میدان','MRI، تشدید مغناطیسی'),
 'ultrasound':('موج و پژواک','سونوگرافی، آکوستیک'),
 'biomech':('اهرم بازو','بیومکانیک'),
 'network':('شبکه‌ی عصبی','هوش مصنوعی، یادگیری ماشین'),
 'microscope':('میکروسکوپ','بافت‌شناسی، پاتولوژی، سلولی'),
 'microbe':('ویروس و آنتی‌بادی','میکروب‌شناسی، ایمنی‌شناسی'),
 'dose':('منحنی دوز و پاسخ','فارماکولوژی'),
 'code':('آکولاد کد','برنامه‌نویسی، کامپیوتر'),
 'book':('کتاب باز','هر درس دیگر'),
}
out=['// Generated by app/scripts/cover-motifs.py (edit that, not this file); kept as plain data so the app and the panel draw the same pictures.',
     "import type { CoverPalette } from './cover';",'',
     '/** Extra motifs: key → SVG elements; @L@ main line, @S@ soft line, @B@ cover background. */',
     'const EXTRA: Record<string, string> = {']
for k,v in M.items():
    body=''.join(v).replace('${L}','@L@').replace('${S}','@S@').replace('${B}','@B@')
    import json as _j
    out.append(f'  {k}: {_j.dumps(body, ensure_ascii=False)},')
out.append('};')
out+=['',"export const EXTRA_MOTIFS = Object.keys(EXTRA);",'',
'export function extraMotif(motif: string, p: CoverPalette): string | null {',
'  const svg = EXTRA[motif];',
'  if (!svg) return null;',
"  return svg.split('@L@').join(p.line).split('@S@').join(p.soft).split('@B@').join(p.bg);",'}','']
open(sys.argv[1],'w').write('\n'.join(out))
# Python choices for Django
with open(sys.argv[2],'w') as fh:
    for k,(name,courses) in LABELS.items():
        fh.write(f'        {k.upper()} = "{k}", "{name} ({courses})"\n')
print(len(M))
