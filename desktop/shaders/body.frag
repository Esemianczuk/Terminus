#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 firstRect;
    vec4 secondRect;
    vec4 firstFlowRect;
    vec4 secondFlowRect;
    vec4 firstLeftEyeRect;
    vec4 firstRightEyeRect;
    vec4 secondLeftEyeRect;
    vec4 secondRightEyeRect;
    vec4 firstLeftEyeBounds;
    vec4 firstRightEyeBounds;
    vec4 secondLeftEyeBounds;
    vec4 secondRightEyeBounds;
    vec4 firstEyeShift;
    vec4 secondEyeShift;
    vec4 skinWeights;
    vec2 flowRange;
    float phase;
    float clock;
    float intensity;
    float morphStrength;
    float gazeStride;
    vec4 backgroundTL;
    vec4 backgroundTR;
    vec4 backgroundBL;
    vec4 backgroundBR;
    vec4 backgroundState;
    vec4 displayEffects;
    vec4 bodyRect;
    vec4 bodyTransform;
} ubuf;
layout(binding = 1) uniform sampler2D bodyAtlas;
layout(binding = 2) uniform sampler2D forwardAtlas;
layout(binding = 3) uniform sampler2D backwardAtlas;
layout(binding = 4) uniform sampler2D gazeAtlas;

vec2 atlasUv(vec2 uv, vec4 rect) { return rect.xy + clamp(uv, vec2(0.0), vec2(1.0)) * rect.zw; }
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
    return mix(mix(hash(i),hash(i+vec2(1,0)),f.x), mix(hash(i+vec2(0,1)),hash(i+1.0),f.x), f.y);
}
vec3 palette(float v, vec3 low, vec3 mid, vec3 high) {
    return mix(mix(low,mid,smoothstep(0.0,.55,v)),high,smoothstep(.55,1.0,v));
}
vec2 desktopUv(vec2 uv) {
    vec2 pivot=ubuf.bodyRect.zw*.5+vec2(0,ubuf.bodyTransform.z);
    vec2 local=uv*ubuf.bodyRect.zw-pivot;
    local.x*=ubuf.bodyTransform.y;
    float angle=radians(ubuf.bodyTransform.x),c=cos(angle),s=sin(angle);
    local=vec2(c*local.x-s*local.y,s*local.x+c*local.y);
    return clamp((local+pivot+ubuf.bodyRect.xy)/vec2(440,340),0.,1.);
}
vec3 background(vec2 p) {
    return mix(mix(ubuf.backgroundTL.rgb,ubuf.backgroundTR.rgb,p.x),
               mix(ubuf.backgroundBL.rgb,ubuf.backgroundBR.rgb,p.x),p.y);
}
float glyph(vec2 q,float luma) {
    // Analytic monospace . : / x + o #. Smooth coverage scales with the body.
    vec2 a=abs(q);
    float aa=max(fwidth(q.x),fwidth(q.y))*.65;
    float dotMark=1.-smoothstep(.07-aa,.07+aa,length(q-vec2(0,.24)));
    if(luma<.16) return dotMark;
    if(luma<.29) return max(dotMark,1.-smoothstep(.07-aa,.07+aa,length(q+vec2(0,.16))));
    float slash=1.-smoothstep(.05-aa,.05+aa,abs(q.x+q.y*.7));
    if(luma<.40) return slash;
    float cross=max(slash,1.-smoothstep(.05-aa,.05+aa,abs(q.x-q.y*.7)));
    if(luma<.52) return cross;
    float plus=1.-smoothstep(.045-aa,.045+aa,min(a.x,a.y));
    if(luma<.65) return plus;
    float ring=1.-smoothstep(.045-aa,.045+aa,abs(length(q*vec2(1.,.8))-.27));
    if(luma<.79) return ring;
    return max(1.-smoothstep(.042-aa,.042+aa,abs(a.x-.14)),
               1.-smoothstep(.042-aa,.042+aa,abs(a.y-.17)));
}
vec4 eyeLayer(vec4 source, vec2 uv, vec4 bounds, vec4 tile, vec2 shift) {
    vec2 local=(uv-bounds.xy)/bounds.zw;
    if (any(lessThan(local,vec2(0))) || any(greaterThan(local,vec2(1))) || dot(shift,shift)<.000000000001) return source;
    vec4 irisRect=tile+vec4(ubuf.gazeStride,0,0,0);
    vec4 maskRect=tile+vec4(ubuf.gazeStride*2.0,0,0,0);
    float aperture=texture(gazeAtlas,atlasUv(local,maskRect)).r;
    if (aperture<=.00001) return source;
    vec3 plate=texture(gazeAtlas,atlasUv(local,tile)).rgb;
    vec4 neutral=texture(gazeAtlas,atlasUv(local,irisRect));
    vec4 moved=texture(gazeAtlas,atlasUv(local-shift/bounds.zw,irisRect));
    vec3 delta=(moved.rgb-plate*moved.a)-(neutral.rgb-plate*neutral.a);
    source.rgb=clamp(source.rgb+delta*aperture,vec3(0),vec3(source.a));
    return source;
}
void main() {
    vec2 uv = qt_TexCoord0;
    float t = clamp(ubuf.phase, 0.0, 1.0);
    vec4 flow = texture(forwardAtlas, atlasUv(uv, ubuf.firstFlowRect));
    vec4 reverse = texture(backwardAtlas, atlasUv(uv, ubuf.firstFlowRect));
    float confidence = reverse.b;
    vec2 fwd = (flow.rg*255.0-128.0)/127.0 * ubuf.flowRange;
    vec2 bwd = (reverse.rg*255.0-128.0)/127.0 * ubuf.flowRange;
    float warp = ubuf.morphStrength * confidence;
    vec2 ua = uv-t*fwd*warp, ub = uv-(1.0-t)*bwd*warp;
    vec4 first = texture(bodyAtlas, atlasUv(ua, ubuf.firstRect));
    vec4 second = texture(bodyAtlas, atlasUv(ub, ubuf.secondRect));
    first=eyeLayer(first,ua,ubuf.firstLeftEyeBounds,ubuf.firstLeftEyeRect,ubuf.firstEyeShift.xy);
    first=eyeLayer(first,ua,ubuf.firstRightEyeBounds,ubuf.firstRightEyeRect,ubuf.firstEyeShift.zw);
    second=eyeLayer(second,ub,ubuf.secondLeftEyeBounds,ubuf.secondLeftEyeRect,ubuf.secondEyeShift.xy);
    second=eyeLayer(second,ub,ubuf.secondRightEyeBounds,ubuf.secondRightEyeRect,ubuf.secondEyeShift.zw);
    vec4 source;
    // At rest the displacement is exactly zero; the authored eye bytes remain.
    if (t <= 0.00001) source = first;
    else if (t >= .99999) source = second;
    else source = mix(first, second, t);
    if (source.a <= .001) { fragColor = vec4(0.0); return; }
    float eyeA = texture(forwardAtlas, atlasUv(ua, ubuf.firstFlowRect)).b;
    float eyeB = texture(forwardAtlas, atlasUv(ub, ubuf.secondFlowRect)).b;
    // A protected eye in either contributing pose vetoes pigment entirely.
    float skin = min(eyeA, eyeB);
    vec3 base = source.rgb / source.a;
    float broad = noise(uv*vec2(7,8)), fine = noise(uv*vec2(25,27));
    float cells = pow(max(0.0, 1.0-length(fract(uv*vec2(32,35))-.5)*1.9),3.0);
    float band = .5+.5*sin(8.0*uv.x+5.0*uv.y-ubuf.clock*1.6+broad*3.0);
    float glint = pow(max(0.0,cos(15.0*uv.y-8.0*uv.x-ubuf.clock*1.8+broad*4.0)),12.0);
    float wave = .5+.5*sin(uv.y*14.0-uv.x*5.0-ubuf.clock*2.1+broad*3.5);
    float reveal = smoothstep(.22,.78,.5+.5*sin(ubuf.clock*.48+broad*7.0+fine*1.3));
    float pulse = .5+.5*sin(uv.y*11.0+uv.x*4.0-ubuf.clock*1.3+broad*3.0);
    vec4 coverage = vec4(.20+.30*band+.26*glint*cells,
                        .32+.52*smoothstep(.48,.9,wave)+.12*cells*smoothstep(.48,.9,wave),
                        .50+.36*reveal+.13*cells, .66+.25*pulse+.08*cells) * ubuf.skinWeights;
    vec3 camo=palette(broad*.72+reveal*.28,vec3(.14,.25,.28),vec3(.44,.56,.36),vec3(.77,.62,.41));
    // The four-color field contains no legible image. Its coordinates follow
    // the desktop while chromatophore islands follow the creature's skin.
    vec2 desktop=desktopUv(uv);
    vec3 sampled=background(desktop);
    float pigmentCell=smoothstep(.28,.73,broad*.72+fine*.28+sin(ubuf.clock*.27)*.07);
    sampled*=.90+.38*pigmentCell;
    camo=mix(camo,sampled,ubuf.backgroundState.x);
    vec3 tint = palette(band,vec3(.09,.76,.83),vec3(.56,.32,.94),vec3(.82,.70,.98))*coverage.x
              +palette(wave,vec3(.10,.78,.72),vec3(.37,.24,.88),vec3(.91,.42,.67))*coverage.y
              +camo*coverage.z
              +palette(pulse,vec3(.30,.045,.16),vec3(.74,.075,.18),vec3(.98,.28,.16))*coverage.w;
    float amount = dot(coverage,vec4(1));
    tint /= max(amount,.00001);
    float light = dot(base,vec3(.2126,.7152,.0722));
    tint *= .16+1.13*light;
    // Camouflage follows the backdrop's luminance while preserving painted
    // relief. Other displays keep their existing deeper pigment response.
    tint+=sampled*.24*ubuf.backgroundState.x*coverage.z/max(amount,.00001);
    tint = mix(tint,base,smoothstep(.62,.96,light)*.60);
    vec3 result = mix(base,tint,clamp(amount*ubuf.intensity*skin,0.0,.94));
    float alpha=source.a;
    float ascii=ubuf.displayEffects.x;
    if(ascii>.0001 && skin>.0001) {
        vec2 grid=vec2(48,52), cell=(floor(uv*grid)+.5)/grid;
        vec4 cellColor=mix(texture(bodyAtlas,atlasUv(cell,ubuf.firstRect)),texture(bodyAtlas,atlasUv(cell,ubuf.secondRect)),t);
        vec3 cellRgb=cellColor.rgb/max(cellColor.a,.001);
        float density=clamp(dot(cellRgb,vec3(.2126,.7152,.0722))*1.35,0.,1.);
        vec2 q=fract(uv*grid)-.5;
        float letter=glyph(q,density)*(1.-smoothstep(.38,.49,abs(q.x)))*(1.-smoothstep(.42,.5,abs(q.y)));
        float islands=noise(uv*vec2(5,6)+vec2(ubuf.clock*.025,-ubuf.clock*.04));
        float dissolve=smoothstep(islands-.13,islands+.13,ascii*1.4-.2)*skin;
        vec3 symbolColor=mix(result,vec3(.55,.96,.91),.35);
        result=mix(result,symbolColor,dissolve);
        alpha*=mix(1.,.025+.975*letter,dissolve);
    }
    fragColor = vec4(clamp(result,0.0,1.0)*alpha,alpha) * ubuf.qt_Opacity;
}
