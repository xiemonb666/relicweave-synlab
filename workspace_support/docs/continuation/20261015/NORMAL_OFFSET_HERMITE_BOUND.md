# Normal-offset cubic fitting: a reusable error bound

Root derivation for the reference-profile geometry adapter. This is a mathematical
bound for a corresponding-parameter offset curve approximation, not a proof of
global vessel wall thickness or real-object similarity.

Let a regular cubic Bezier meridian be gamma(t)=(r(t),z(t)), t in [0,1]. Write
v=gamma', a=gamma'', b=gamma''' (constant). For a bottom-to-rim inner wall,
the outward right normal is N=(z',-r')/|v|. The designed outer curve is
f=gamma+d*N, where d is the positive normal-offset distance in millimetres.
The derivative is f'=gamma'+d*N'. A cubic Hermite interpolant on [s0,s1]
uses f and f' at the endpoints, precisely the cubic fit used by the adapter.

Obtain conservative bounds V>=sup|v|, A>=sup|a|, B=|b| and wm<=inf|v|^2,
with wm>0. Bezier derivative control points provide convex-hull upper bounds;
the distance of their component interval box from the origin gives a simple
valid lower speed bound when positive. If it is zero, subdivide or use the
distance to the derivative control-point convex hull; do not manufacture a
positive lower bound from finite samples.

For w=|v|^2 and g=w^(-1/2), conservative absolute derivative bounds are

```
W1 = 2 V A
W2 = 2 A^2 + 2 V B
W3 = 6 A B
W4 = 6 B^2

G2 = (3/4) wm^(-5/2) W1^2 + (1/2) wm^(-3/2) W2
G3 = (15/8) wm^(-7/2) W1^3
     + (9/4) wm^(-5/2) W1 W2 + (1/2) wm^(-3/2) W3
G4 = (105/16) wm^(-9/2) W1^4
     + (45/4) wm^(-7/2) W1^2 W2
     + (9/4) wm^(-5/2) W2^2
     + 3 wm^(-5/2) W1 W3 + (1/2) wm^(-3/2) W4
```

Since N=v_perp*g and the third derivative of v vanishes,

```
sup |f''''| <= d (V G4 + 4 A G3 + 6 B G2) = M4.
```

The scalar Hermite remainder is bounded by M4*(s1-s0)^4/384. Applying
the scalar bound to both coordinates gives the safe Euclidean bound
sqrt(2)*M4*(s1-s0)^4/384. A sharper vector Peano-kernel bound is possible
but is unnecessary for a conservative implementation. Parameter derivatives
and interval widths must use the same original Bezier parameterization.

The current three interior fit probes only measure sampled deviation. Until
this interval/remainder bound is implemented and independently checked, their
maximum must be labeled sampled, even when it is below the desired tolerance.
CAD validity, curve/solid self-intersection, other meridian segments and foot,
floor or lip junctions require separate checks. Real reference matching and
specimen wall measurements remain separate evidence.
