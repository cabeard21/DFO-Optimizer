"""Independent single-trial scalar replay of a pinned ordinary online melee blow."""
from struct import pack, unpack


def f32(value):
    return unpack("f",pack("f",value))[0]


PARTS=(0,1,1,1,2,2,2,3,3,3,3,4,4,4,5,5,5,5,6,6)
METALS=(-1,0,0,1,2,3,3,4,5,6)


def _reduce(piece, damage, kind, natural):
    if not piece[0]:
        return round(f32(damage*f32(1-natural)))
    cond=100*piece[0]//piece[1]
    wear=1 if cond>=61 else 1.1 if cond>=41 else 1.2 if cond>=16 else 1.35 if cond>=6 else 1.5
    base,limit=piece[4+2*kind:6+2*kind]
    factor=min(f32(f32(base/100)*f32(wear)),f32(limit/100))
    return round(f32(damage*f32(factor-natural)))


def _shield_chance(stats, template, covered):
    index=template-109
    base=((30,35,45,55) if covered else (20,10,5,-5))[index]
    factors=(.3,.3,.3,.2,.1,.1) if covered else (.3,.2,.2,.1,.1,.1)
    total=base
    for i,ratio in zip((3,6,0,4,2,7),factors,strict=True):
        total=f32(total+f32((stats[i]-50)*f32(ratio)))
    return round(total)


def melee_blow(attacker, target, player, hp_a, max_a, hp_t, max_t, rng):
    weapon=attacker["weapon"]
    armed=weapon[2]>0
    spec=attacker["armed"] if armed else attacker["bare"]
    skill,lo,hi,bonus_damage,bonus_hit,two,blunt,*_=spec
    a,t=attacker["stats"],target["stats"]
    mat=METALS[weapon[1]] if armed else 0
    crit=int(rng.next()*100)<int(attacker["crit"]/(4-(a[7]-50)//25))
    part=PARTS[int(20*rng.next())]
    diff=int((a[7]-t[7])/10)+int((a[3]-t[3])/4)+int((a[6]-t[6])/8)-round(f32((t[7]-50)/10))
    chance=(3*skill+1)//2+diff-target["dodge"]//2+(10 if player else 50)
    chance+=8*(int(bool(attacker["adrenaline"] and hp_a<max_a//6))-int(bool(target["adrenaline"] and hp_t<max_t//6)))
    chance+=(attacker["crit"]//4 if crit else 0)+(bonus_hit if player else 0)+(2*mat+2 if armed else 0)
    hit=int(rng.next()*100)<max(3,min(97,chance))
    damage=0
    if hit and (player or armed):
        damage=lo+int(rng.next()*(hi+1-lo))+(bonus_damage if player else 0)
        if armed and player and target["index"]==15:
            # All admitted ordinary items have the source's default zero flags.
            damage//=2
            if weapon[1]==2: damage*=2
        elif armed and player and target["index"] in (9,18,14) and weapon[1]==2:
            damage*=2
        damage+=((a[0]-50)//10)*(2 if two else 1)+mat
        if damage>0:
            will=int((a[2]-50)/5)
            magnitude=max(0,10+will-target["level"]//2 if player else 5+will+attacker["level"]//4)
            random_bonus=int(rng.next()*magnitude) if magnitude else 0
            group=target["group"]
            if group>=0:
                if attacker["attack_flags"] & (1<<group):
                    damage+=random_bonus
                elif attacker["attack_flags"] & (16<<group):
                    damage-=max(0,target["level"]//2-will if player else target["level"]-attacker["level"]-will)
    damage=max(0,damage)
    if crit:
        damage=round(f32(damage*f32(1+f32((attacker["crit"]//5)*f32(.05)))))
    if armed and weapon[1]<target["min_metal"]:
        damage=round(f32(damage*f32(1-min(f32(.9),f32((target["min_metal"]-weapon[1])*f32(.2))))))
    natural=f32(f32((t[4]-50)*f32(.002)) + f32((t[0]-50)*f32(.001)))
    natural=f32(natural + f32((t[2]-50)*f32(.001)))
    piece,shield=target["armor"][part],target["armor"][7]
    covered=bool(shield[0] and shield[3]&(1<<part))
    block=False
    if shield[0]:
        block=(int(100*rng.next())<_shield_chance(t,shield[2],covered)
               and _reduce(shield,100,3,natural)<=_reduce(piece,100,3,natural))
    if armed and player:
        pct=100*weapon[2]//weapon[3]
        multiplier=(1 if pct>=61 else (.9 if blunt else .85) if pct>=41 else
                    (.8 if blunt else .7) if pct>=16 else (.65 if blunt else .45) if pct>=6 else (.5 if blunt else .25))
        damage=round(f32(damage*f32(multiplier)))
    if damage:
        damage=_reduce(shield if block else piece,damage,0 if not armed else 1 if blunt else 2,natural)
    if armed and damage>0:
        migrated_max=attacker.get("repool",0)
        if migrated_max:
            weapon[2]=int(weapon[2]*migrated_max/weapon[3]+.5)
            weapon[3]=migrated_max
            attacker["repool"]=0
        for worn in (weapon,shield if covered else piece):
            index=2 if worn is weapon else 0
            if worn[index]:
                wear=(damage+5)//10
                if wear==0:
                    wear=int(int(100*rng.next())<20)
                worn[index]=max(0,worn[index]-wear)
    return damage,hit,part
