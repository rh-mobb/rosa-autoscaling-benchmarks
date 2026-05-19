import{p as H}from"./chunk-WASTHULE-MnhXAKvk.js";import{p as J}from"./wardley-RL74JXVD-T2LBEBUU-C51wbk_0.js";import{g as K,s as Y,b as tt,c as et,y as at,x as it,d as s,l as w,e as rt,L as st,aQ as ot,aR as lt,aS as L,aT as nt,h as ct,D as dt,aU as pt,M as gt}from"./two-cols.vue_vue_type_script_setup_true_lang-BIooLUMJ.js";import"./chunk-MFRUYFWM-DWzaVOvm.js";import"./index-CSJ_gwlv.js";import"./modules/vue-Dt4EMbRN.js";import"./modules/shiki-yO8jEN9Y.js";import"./modules/file-saver-B8IIMB9x.js";var ht=gt.pie,D={sections:new Map,showData:!1},u=D.sections,C=D.showData,ut=structuredClone(ht),ft=s(()=>structuredClone(ut),"getConfig"),mt=s(()=>{u=new Map,C=D.showData,dt()},"clear"),vt=s(({label:t,value:a})=>{if(a<0)throw new Error(`"${t}" has invalid value: ${a}. Negative values are not allowed in pie charts. All slice values must be >= 0.`);u.has(t)||(u.set(t,a),w.debug(`added new section: ${t}, with value: ${a}`))},"addSection"),xt=s(()=>u,"getSections"),St=s(t=>{C=t},"setShowData"),wt=s(()=>C,"getShowData"),G={getConfig:ft,clear:mt,setDiagramTitle:it,getDiagramTitle:at,setAccTitle:et,getAccTitle:tt,setAccDescription:Y,getAccDescription:K,addSection:vt,getSections:xt,setShowData:St,getShowData:wt},Dt=s((t,a)=>{H(t,a),a.setShowData(t.showData),t.sections.map(a.addSection)},"populateDb"),Ct={parse:s(async t=>{const a=await J("pie",t);w.debug(a),Dt(a,G)},"parse")},yt=s(t=>`
  .pieCircle{
    stroke: ${t.pieStrokeColor};
    stroke-width : ${t.pieStrokeWidth};
    opacity : ${t.pieOpacity};
  }
  .pieOuterCircle{
    stroke: ${t.pieOuterStrokeColor};
    stroke-width: ${t.pieOuterStrokeWidth};
    fill: none;
  }
  .pieTitleText {
    text-anchor: middle;
    font-size: ${t.pieTitleTextSize};
    fill: ${t.pieTitleTextColor};
    font-family: ${t.fontFamily};
  }
  .slice {
    font-family: ${t.fontFamily};
    fill: ${t.pieSectionTextColor};
    font-size:${t.pieSectionTextSize};
    // fill: white;
  }
  .legend text {
    fill: ${t.pieLegendTextColor};
    font-family: ${t.fontFamily};
    font-size: ${t.pieLegendTextSize};
  }
`,"getStyles"),$t=yt,Tt=s(t=>{const a=[...t.values()].reduce((r,l)=>r+l,0),y=[...t.entries()].map(([r,l])=>({label:r,value:l})).filter(r=>r.value/a*100>=1);return pt().value(r=>r.value).sort(null)(y)},"createPieArcs"),At=s((t,a,y,$)=>{var z;w.debug(`rendering pie chart
`+t);const r=$.db,l=rt(),T=st(r.getConfig(),l.pie),A=40,o=18,p=4,c=450,d=c,f=ot(a),n=f.append("g");n.attr("transform","translate("+d/2+","+c/2+")");const{themeVariables:i}=l;let[_]=lt(i.pieOuterStrokeWidth);_??(_=2);const b=T.textPosition,g=Math.min(d,c)/2-A,B=L().innerRadius(0).outerRadius(g),O=L().innerRadius(g*b).outerRadius(g*b);n.append("circle").attr("cx",0).attr("cy",0).attr("r",g+_/2).attr("class","pieOuterCircle");const h=r.getSections(),P=Tt(h),I=[i.pie1,i.pie2,i.pie3,i.pie4,i.pie5,i.pie6,i.pie7,i.pie8,i.pie9,i.pie10,i.pie11,i.pie12];let m=0;h.forEach(e=>{m+=e});const E=P.filter(e=>(e.data.value/m*100).toFixed(0)!=="0"),v=nt(I).domain([...h.keys()]);n.selectAll("mySlices").data(E).enter().append("path").attr("d",B).attr("fill",e=>v(e.data.label)).attr("class","pieCircle"),n.selectAll("mySlices").data(E).enter().append("text").text(e=>(e.data.value/m*100).toFixed(0)+"%").attr("transform",e=>"translate("+O.centroid(e)+")").style("text-anchor","middle").attr("class","slice");const N=n.append("text").text(r.getDiagramTitle()).attr("x",0).attr("y",-400/2).attr("class","pieTitleText"),k=[...h.entries()].map(([e,S])=>({label:e,value:S})),x=n.selectAll(".legend").data(k).enter().append("g").attr("class","legend").attr("transform",(e,S)=>{const F=o+p,Z=F*k.length/2,j=12*o,q=S*F-Z;return"translate("+j+","+q+")"});x.append("rect").attr("width",o).attr("height",o).style("fill",e=>v(e.label)).style("stroke",e=>v(e.label)),x.append("text").attr("x",o+p).attr("y",o-p).text(e=>r.getShowData()?`${e.label} [${e.value}]`:e.label);const U=Math.max(...x.selectAll("text").nodes().map(e=>(e==null?void 0:e.getBoundingClientRect().width)??0)),Q=d+A+o+p+U,R=((z=N.node())==null?void 0:z.getBoundingClientRect().width)??0,V=d/2-R/2,X=d/2+R/2,M=Math.min(0,V),W=Math.max(Q,X)-M;f.attr("viewBox",`${M} 0 ${W} ${c}`),ct(f,c,W,T.useMaxWidth)},"draw"),_t={draw:At},Gt={parser:Ct,db:G,renderer:_t,styles:$t};export{Gt as diagram};
