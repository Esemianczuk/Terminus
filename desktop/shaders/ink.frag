#version 440
layout(location=0) in vec2 qt_TexCoord0;
layout(location=0) out vec4 fragColor;
layout(std140,binding=0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 bodyRect;
    vec4 backgroundTL;
    vec4 backgroundTR;
    vec4 backgroundBL;
    vec4 backgroundBR;
    vec4 backgroundState;
    vec4 displayEffects;
    vec4 windowField0;
    vec4 windowField1;
    vec4 windowField2;
    vec4 windowField3;
} ubuf;
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise(vec2 p){
    vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
    return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1)),f.x),f.y);
}
float fbm(vec2 p){return .57*noise(p)+.28*noise(p*2.03+3.1)+.15*noise(p*4.07+7.3);}
vec2 windowFlow(vec2 p,vec4 r){
    if(r.z<=0. || r.w<=0.) return vec2(0);
    vec2 center=r.xy+r.zw*.5;
    vec2 d=p-center;
    vec2 q=abs(d)-r.zw*.5;
    float edge=length(max(q,vec2(0)))+min(max(q.x,q.y),0.);
    // Soft tangential flow around geometry, never a drawn rectangle.
    float influence=exp(-edge*edge/0.012);
    vec2 tangent=normalize(vec2(-d.y,d.x)+vec2(.0001));
    return tangent*influence*.08;
}
void main(){
    vec2 uv=qt_TexCoord0;
    float age=ubuf.displayEffects.z,seed=ubuf.displayEffects.w*23.7;
    vec2 origin=(ubuf.bodyRect.xy+ubuf.bodyRect.zw*vec2(.52,.79))/vec2(440,340);
    vec2 p=(uv-origin)*vec2(1.294,1.);
    vec2 currents=windowFlow(uv,ubuf.windowField0)+windowFlow(uv,ubuf.windowField1)
                 +windowFlow(uv,ubuf.windowField2)+windowFlow(uv,ubuf.windowField3);
    p-=currents*(.3+ubuf.backgroundState.y*.7);
    p-=ubuf.backgroundState.zw*age*.017;
    p.y+=age*.014;
    float expansion=.13+.024*age;
    vec2 advect=p*5.7+vec2(seed,-age*.15);
    vec2 warp=vec2(fbm(advect+vec2(0,age*.06)),fbm(advect+vec2(4.7,-age*.04)))-.5;
    vec2 folded=p+warp*(.075+age*.008);
    float billow=fbm(folded*12.+vec2(seed,age*.1));
    float core=exp(-dot(folded/vec2(expansion,expansion*.8),folded/vec2(expansion,expansion*.8))*1.5);
    vec2 curled=folded-vec2(sin(age*.45+seed)*.07,-expansion*.75);
    float lobe=exp(-dot(curled/vec2(expansion*.8,expansion),curled/vec2(expansion*.8,expansion))*2.3);
    float density=smoothstep(.08,.65,(core+lobe*.65)*(.42+billow*.88));
    float wisp=smoothstep(.46,.78,billow)*exp(-dot(p,p)/(expansion*expansion*3.))* .28;
    float border=smoothstep(0.,.055,uv.x)*smoothstep(0.,.055,uv.y)*smoothstep(0.,.055,1.-uv.x)*smoothstep(0.,.055,1.-uv.y);
    float alpha=clamp((density*.61+wisp)*ubuf.displayEffects.y*border,0.,.70);
    vec3 backdrop=mix(mix(ubuf.backgroundTL.rgb,ubuf.backgroundTR.rgb,uv.x),mix(ubuf.backgroundBL.rgb,ubuf.backgroundBR.rgb,uv.x),uv.y);
    float luminance=dot(backdrop,vec3(.2126,.7152,.0722));
    vec3 dark=vec3(.055,.025,.12),light=vec3(.25,.40,.50);
    vec3 ink=mix(light,dark,smoothstep(.25,.65,luminance)*ubuf.backgroundState.x);
    float rim=pow(max(0.,billow-.39),2.)*1.8;
    ink+=vec3(.07,.24,.30)*rim;
    fragColor=vec4(ink*alpha,alpha)*ubuf.qt_Opacity;
}
