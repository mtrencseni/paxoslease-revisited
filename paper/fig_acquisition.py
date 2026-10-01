"""Figure: one PaxosLease acquisition as a message-sequence diagram, in black.

Adapted from the companion relativity note's Figure 2.  Regenerate with: cd paper && python3 fig_acquisition.py
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.size':7,'font.family':'serif',
                     'font.serif':['STIXGeneral','DejaVu Serif'],
                     'mathtext.fontset':'stix','axes.linewidth':0.8})
C_OLD = C_ARR = 'black'
LW_WORLD, LW_ARROW = 1.4, 1.0
MS_EVENT = 5.0
FS_AXIS, FS_EVENT, FS_ANNOT = 7.0, 7.5, 6.4
BOX = dict(boxstyle='round,pad=0.30', fc='white', ec='black', lw=0.6)

def axis_arrow(ax,p0,p1,color):
    """One axis: a thin arrow.  An arrowhead means an axis; worldlines have none."""
    ax.annotate('',xy=p1,xytext=p0,annotation_clip=False,
                arrowprops=dict(arrowstyle='-|>,head_width=0.16,head_length=0.38',
                                color=color,lw=0.8,shrinkA=0,shrinkB=0))


# A message-sequence diagram, not a spacetime diagram: time runs up, horizontal
# position only separates the participants, and every message arrow is level so
# that no arrow can be read as a trajectory.
fig,ax=plt.subplots(figsize=(3.35,2.25))
P,A=0.0,(1.60,2.40,3.20)
TOP=3.85
ax.set_xlim(-1.62,4.85)
ax.set_ylim(-0.10,TOP+0.55)
ax.set_xticks([])
ax.set_yticks([])
for sp in ('top','right','left','bottom'):
    ax.spines[sp].set_visible(False)
axis_arrow(ax,(-1.26,0.0),(-1.26,TOP+0.40),'black')
ax.text(-1.52,TOP*0.55,'time',color='black',fontsize=FS_AXIS,rotation=90,va='center')
for x,lab,c in [(P,'proposer',C_OLD)]+[(A[i],'acceptor %d'%(i+1),C_ARR) for i in range(3)]:
    ax.plot([x,x],[0.0,TOP],'-',color=c,lw=LW_WORLD)
    ax.text(x,TOP+0.12,lab,color=c,fontsize=FS_ANNOT,ha='center')
def arrow(t,x0,x1,c):
    ax.annotate('',xy=(x1,t),xytext=(x0,t),
                arrowprops=dict(arrowstyle='-|>',color=c,lw=LW_ARROW,shrinkA=1.5,shrinkB=1.5))
def group(t0,out,c,lab):
    for i,x in enumerate(A):
        t=t0+0.10*i
        arrow(t,P,x,c) if out else arrow(t,x,P,c)
    ax.text(3.62,t0-0.02,lab,color=c,fontsize=FS_ANNOT,ha='left',va='bottom')
def mark(t,lab):
    ax.plot(P,t,'o',color=C_OLD,ms=MS_EVENT,zorder=6)
    ax.text(P-0.26,t,lab,color=C_OLD,fontsize=FS_ANNOT,ha='right',va='center')
ax.plot(P,0.35,'*',color=C_OLD,ms=MS_EVENT*2.1,zorder=7)
ax.text(P-0.26,0.35,'$D_P$ starts',color=C_OLD,fontsize=FS_ANNOT,ha='right',va='center')
group(0.35,True ,C_OLD,'Prepare')
group(0.70,False,C_ARR,'promises')
mark(0.80,'majority')
group(1.35,True ,C_OLD,'Accept')
group(1.70,False,C_ARR,'acceptances')
mark(1.80,'acquired')
ax.plot([P-0.07,P+0.07],[2.45,2.45],'-',color=C_OLD,lw=LW_ARROW)
ax.text(P-0.26,2.45,'expires',color=C_OLD,fontsize=FS_ANNOT,ha='right',va='center')
ax.annotate('',xy=(P+0.22,2.45),xytext=(P+0.22,0.35),
            arrowprops=dict(arrowstyle='<->',color=C_OLD,lw=LW_ARROW))
ax.text(P+0.29,2.17,'$D_P$',color=C_OLD,fontsize=FS_EVENT,rotation=90,va='center')
for i,x in enumerate(A):
    ax.plot(x,1.35+0.10*i,'*',color=C_ARR,ms=MS_EVENT*2.1,zorder=7)
ax.text(A[0]-0.08,1.20,'$D_A$ starts',color=C_ARR,fontsize=FS_ANNOT,ha='right',va='top')
for i,x in enumerate(A):
    ax.annotate('',xy=(x+0.14,3.55+0.10*i),xytext=(x+0.14,1.35+0.10*i),
                arrowprops=dict(arrowstyle='<->',color=C_ARR,lw=LW_ARROW))
ax.text(A[0]+0.20,2.20,'$D_A$',color=C_ARR,fontsize=FS_EVENT,rotation=90,va='center')
ax.axhspan(2.45,3.55,xmin=0.05,xmax=0.79,color='black',alpha=0.08,lw=0,zorder=0)
ax.text(1.35,3.00,"the proposer's lease timer has expired, but\nthe acceptors' timers have not, so no other\nproposer can acquire the lease here.",
        color=C_ARR,fontsize=FS_ANNOT,ha='center',va='center',linespacing=1.4,bbox=BOX,zorder=8)
fig.tight_layout()
fig.savefig('fig-acquisition.pdf')
plt.close(fig)
