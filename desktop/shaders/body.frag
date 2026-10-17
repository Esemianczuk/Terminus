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
    vec4 skinWeights;
    vec2 flowRange;
    float phase;
    float clock;
    float intensity;
    float morphStrength;
} ubuf;
layout(binding = 1) uniform sampler2D bodyAtlas;
layout(binding = 2) uniform sampler2D forwardAtlas;
layout(binding = 3) uniform sampler2D backwardAtlas;

vec2 atlasUv(vec2 uv, vec4 rect) { return rect.xy + clamp(uv, vec2(0.0), vec2(1.0)) * rect.zw; }
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
    return mix(mix(hash(i),hash(i+vec2(1,0)),f.x), mix(hash(i+vec2(0,1)),hash(i+1.0),f.x), f.y);
}
vec3 palette(float v, vec3 low, vec3 mid, vec3 high) {
    return mix(mix(low,mid,smoothstep(0.0,.55,v)),high,smoothstep(.55,1.0,v));
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
    vec4 source;
    // Exact endpoints preserve the authored image, including eye/alpha bytes.
    if (t <= 0.00001) source = texture(bodyAtlas, atlasUv(uv, ubuf.firstRect));
    else if (t >= .99999) source = texture(bodyAtlas, atlasUv(uv, ubuf.secondRect));
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
    vec3 tint = palette(band,vec3(.09,.76,.83),vec3(.56,.32,.94),vec3(.82,.70,.98))*coverage.x
              +palette(wave,vec3(.10,.78,.72),vec3(.37,.24,.88),vec3(.91,.42,.67))*coverage.y
              +palette(broad*.72+reveal*.28,vec3(.14,.25,.28),vec3(.44,.56,.36),vec3(.77,.62,.41))*coverage.z
              +palette(pulse,vec3(.30,.045,.16),vec3(.74,.075,.18),vec3(.98,.28,.16))*coverage.w;
    float amount = dot(coverage,vec4(1));
    tint /= max(amount,.00001);
    float light = dot(base,vec3(.2126,.7152,.0722));
    tint *= .16+1.13*light;
    tint = mix(tint,base,smoothstep(.62,.96,light)*.60);
    vec3 result = mix(base,tint,clamp(amount*ubuf.intensity*skin,0.0,.94));
    fragColor = vec4(clamp(result,0.0,1.0)*source.a,source.a) * ubuf.qt_Opacity;
}
