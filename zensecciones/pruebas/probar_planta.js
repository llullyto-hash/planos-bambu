// Prueba rápida de la lectura de planta sin abrir el navegador:
//   node pruebas/probar_planta.js programa/ZenSecciones.html "ruta/planta.dxf"
// Muestra las capas asignadas a cada papel y lo leído en cada progresiva.
const fs=require('fs'),path=require('path'),vm=require('vm');
const [html,dxf]=process.argv.slice(2);
const L=fs.readFileSync(html,'utf8').split('\n');
const a=L.findIndex(l=>l.startsWith('const ST={')),b=L.findIndex(l=>l.startsWith('// PASO 3'));
let code=L.slice(a,b-1).join('\n').replace("const $=s=>document.querySelector(s);","const $=s=>({value:'',innerHTML:''});");
code+=`\nfunction loadData(d){globalThis.OUT=d}\nfunction stat(id,l){console.log(l.map(x=>x[1]).join(' | '))}\nfunction renderRoles(){}\n`+
  `globalThis.run=t=>{PL=parseDXF(t);PL.name=${JSON.stringify(path.basename(dxf))};PL.roles=autoRoles(PL.layers);console.log('Capas:',PL.roles);procesarPlanta()}`;
vm.runInThisContext(code);
const buf=fs.readFileSync(dxf);let t=new TextDecoder('utf-8').decode(buf);if(t.includes('�'))t=new TextDecoder('windows-1252').decode(buf);
run(t);
const sv=v=>v?`${v.calz}${v.ber?'+b'+v.ber:''} | ${v.cun==='ninguna'?(v.sar?'sard '+v.sar:'-'):v.cun+' '+v.cunA} | ${v.fr} | ${v.ver}`:'—';
OUT.forEach(c=>{const n={};c.sts.forEach(x=>n[x.s]=(n[x.s]||0)+1);console.log(`\n${c.name} · ${c.L.toFixed(1)} m ·`,n);
  c.sts.forEach(x=>console.log(String(x.st).padStart(8),x.s.padEnd(5),'izq',sv(x.L).padEnd(34),'der',sv(x.R).padEnd(34),x.m||''))});
