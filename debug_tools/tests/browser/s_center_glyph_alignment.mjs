// 使用调试平台真实 CSS / HarmonyOS 字体验证可见字底，而不是仅比较文字框。
// node s_center_glyph_alignment.mjs <宽> <高> <输出目录> <浏览器路径> [缩放]
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildSync } from 'esbuild';
import { chromium } from 'playwright-core';

const [widthArg, heightArg, outputArg, browserPath, scaleArg = '1'] = process.argv.slice(2);
const width = Number(widthArg), height = Number(heightArg), scale = Number(scaleArg);
assert(width > 0 && height > 0 && scale > 0 && outputArg && browserPath,
  '必须显式指定卡片宽高、输出目录、浏览器；缩放可选');
const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const debugRoot = path.join(repository, 'debug_tools');
const output = path.resolve(outputArg);
mkdirSync(output, { recursive: true });
const python = String.raw`
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('widget_service/cloud').resolve()))
from services.compact.compact_dsl_a2ui_converter import convert_compact_dsl_to_a2ui
samples=[]
for label, value, unit, subtitle in [
    ('学校秋季运动会开幕倒计时',58,'天','距12月26日'),
    ('运动会\n倒计时',102,'天',None),
    ('耳机电量',85,'%','左耳'),
    ('电量变化',-8.5,'%',None),
    ('运动会还剩',120,'天','2027年5月1日'),
]:
    props={
        'label':{'path':'/data/title'},
        'value':value,'unit':unit,'fontColor':'#FFFFFFFF',
    }
    if subtitle is not None:
        props['secondaryInfo']=('{{ ' + '$' + '{/data/subtitle} }}') if label=='耳机电量' else {'path':'/data/subtitle'}
    rows=[
        ['root','Layout',{'layout':'S-center','backgroundColor':'#FF9C4E22'},['display']],
        ['display','DataDisplay',props],
        ['/data/subtitle',subtitle or ''],
        ['/data/title',label],
    ]
    source='\n'.join(json.dumps(row,ensure_ascii=False) for row in rows)
    converted=convert_compact_dsl_to_a2ui(source,size='2x2')
    for line in converted.splitlines():
        for node in json.loads(line).get('updateComponents',{}).get('components',[]):
            if node.get('component')=='Text' and 'lineHeight' in node.get('styles',{}):
                raise RuntimeError('S-center numeric Text must use default line height')
    samples.append(converted)
print(json.dumps(samples,ensure_ascii=False))
`;
const sources = JSON.parse(execFileSync('uv', ['run', '--no-sync', 'python', '-c', python], {
  cwd: repository, encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
}));
sources.forEach((source,index)=>writeFileSync(path.join(output,`sample-${index}.a2ui.jsonl`),source));
let css = readFileSync(path.join(debugRoot, 'card_renderer/frontend/src/styles.css'), 'utf8');
css = css.replace(/url\("\/fonts\/harmonyos\/([^"]+)"\)/g, (_, name) =>
  'url("data:font/ttf;base64,' + readFileSync(path.join(debugRoot,
    'card_renderer/assets/fonts/harmonyos', name)).toString('base64') + '")');
const app = `import React from 'react';import {createRoot} from 'react-dom/client';
import {UIGraph} from './card_renderer/runtime/graph/src/graph.ts';
import {JsonlStreamParser} from './card_renderer/runtime/parser/src/parser.ts';
import {renderTree,defaultRegistry} from './card_renderer/runtime/renderer/src/index.ts';
window.React=React;
window.subtitleUpdaters={};
window.titleUpdaters={};
const sources=${JSON.stringify(sources)};
for(let i=0;i<sources.length;i++){
 const graph=new UIGraph();
 const parser=new JsonlStreamParser({onMessage:c=>graph.applyCommand(c),onParseError:(_,e)=>{throw e;}});
 parser.push(sources[i]);parser.end();
 const root=createRoot(document.getElementById('card'+i));
 root.render(renderTree(graph,defaultRegistry));
 window.titleUpdaters[i]=value=>{
   graph.applyCommand({__updateDataModel:{surfaceId:'surface_card',path:'/data/title',value}});
   root.render(renderTree(graph,defaultRegistry));
 };
 if(i===0 || i===2) window.subtitleUpdaters[i]=value=>{
   graph.applyCommand({__updateDataModel:{surfaceId:'surface_card',path:'/data/subtitle',value}});
   root.render(renderTree(graph,defaultRegistry));
 };
}`;
const bundle = buildSync({ stdin: { contents: app, resolveDir: debugRoot, loader: 'tsx' },
  bundle: true, write: false, format: 'iife', jsx: 'transform' }).outputFiles[0].text;
const browser = await chromium.launch({ executablePath: browserPath, headless: true });
try {
  const page = await browser.newPage({ viewport: {
    width: Math.ceil((width * scale + 20) * sources.length + 20),
    height: Math.ceil(height * scale + 40),
  }, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setContent('<meta charset="utf-8"><style>' + css + '</style>' +
    '<style>body.card-renderer{display:flex;height:auto;margin:20px;gap:20px}' +
    `.slot{width:${width * scale}px;height:${height * scale}px;flex-shrink:0}` +
    `.card{width:${width}px;height:${height}px;transform:scale(${scale});transform-origin:top left}` +
    '</style><body class="card-renderer">' + sources.map((_, i) =>
      '<section class="slot"><div class="card" id="card'+i+'"></div></section>').join(''));
  await page.addScriptTag({ content: bundle });
  await page.waitForSelector('#card3 [data-node-id="display_unit"]');
  await page.evaluate(async () => {
    await document.fonts.load('700 46px "HarmonyOS Sans SC"');
    await document.fonts.load('500 16px "HarmonyOS Sans SC"');
    await document.fonts.load('500 12px "HarmonyOS Sans SC"');
    await document.fonts.ready;
  });
  const png = await page.screenshot({ path: path.join(output, 'preview.png') });
  const unclipped = await page.screenshot({ style: [
    '[data-node-id="display_value"], [data-node-id="display_unit"],',
    '[data-node-id="display_secondary"] { overflow: visible !important; }',
  ].join('\n') });
  const evidence = await page.evaluate(async ({dataUrl, unclippedUrl, scale}) => {
    const image = new Image(); image.src = dataUrl; await image.decode();
    const unclippedImage = new Image(); unclippedImage.src = unclippedUrl; await unclippedImage.decode();
    const canvas = document.createElement('canvas');
    canvas.width = image.width; canvas.height = image.height;
    const ctx = canvas.getContext('2d');ctx.drawImage(image,0,0);
    const ratio = image.width / innerWidth;
    function bottom(element) {
      const rect=element.getBoundingClientRect();
      const x0=Math.floor(rect.x*ratio),y0=Math.floor(rect.y*ratio);
      const width=Math.ceil(rect.right*ratio)-x0,height=Math.ceil(rect.bottom*ratio)-y0;
      const pixels=ctx.getImageData(x0,y0,width,height).data;
      let last=-1;
      for(let y=0;y<height;y++)for(let x=0;x<width;x++){
        const i=(y*width+x)*4;
        if(Math.min(pixels[i],pixels[i+1],pixels[i+2])>225)last=y;
      }
      if(last<0)throw Error('没有找到前景字形像素');
      return (y0+last)/ratio;
    }
    return Array.from(document.querySelectorAll('.card')).map(card=>{
      const number=card.querySelector('[data-node-id="display_value"]');
      const unit=card.querySelector('[data-node-id="display_unit"]');
      const numberBottom=bottom(number),unitBottom=bottom(unit);
      const rect = id => card.querySelector('[data-node-id="'+id+'"]').getBoundingClientRect();
      const display=rect('display'), main=rect('display_main_group');
      const area=rect('display_numeric_area'),row=rect('display_value_row');
      const cardBox=card.getBoundingClientRect();
      const label=rect('display_label');
      const subtitle=card.querySelector('[data-node-id="display_secondary"]');
      const subtitleBox=subtitle?.getBoundingClientRect();
      const numberBox=number.getBoundingClientRect(),unitBox=unit.getBoundingClientRect();
      const groupBottom=subtitleBox?.bottom ?? row.bottom;
      const geometry={displayHeight:display.height,labelHeight:label.height,
        mainTopOffset:main.top-display.top,
        mainBottomOffset:main.bottom-(subtitleBox?.top ?? display.bottom),
        groupCenterOffset:(label.top+row.bottom-main.top-main.bottom)/2,
        subtitleBottomInset:subtitleBox && cardBox.bottom-subtitleBox.bottom,
        groupContained:label.top>=display.top-0.1 && groupBottom<=display.bottom+0.1,
        labelWeight:getComputedStyle(card.querySelector('[data-node-id="display_label"]')).fontWeight,
        labelLineHeight:getComputedStyle(card.querySelector('[data-node-id="display_label"]')).lineHeight,
        subtitleHeight:subtitleBox?.height,subtitleGap:subtitleBox && subtitleBox.top-row.bottom,
        subtitleFont:subtitle && getComputedStyle(subtitle).fontSize,
        gap:row.top-label.bottom,
        numericAreaHeight:area.height,rowHeight:row.height,
        rowCenterOffset:(row.top+row.bottom-area.top-area.bottom)/2,
        valueHeight:numberBox.height,unitBoxBottomOffset:unitBox.bottom-numberBox.bottom,
        valueUnitGap:unitBox.left-numberBox.right,
        valueFont:getComputedStyle(number).fontSize,unitFont:getComputedStyle(unit).fontSize,
        valueLineHeight:getComputedStyle(number).lineHeight,unitLineHeight:getComputedStyle(unit).lineHeight};
      const pixels=rect => ctx.getImageData(Math.floor(rect.x*ratio),Math.floor(rect.y*ratio),
        Math.ceil(rect.width*ratio),Math.ceil(rect.height*ratio)).data;
      const normalPixels=pixels(cardBox);
      ctx.drawImage(unclippedImage,0,0);
      const unclippedPixels=pixels(cardBox);
      ctx.drawImage(image,0,0);
      // 与开放溢出的版本对比可见字形，排除文字框边界的抗锯齿色差。
      let clipped=false;
      for(let index=0;index<normalPixels.length;index+=4){
        const original=Math.min(normalPixels[index],normalPixels[index+1],normalPixels[index+2]);
        const exposed=Math.min(unclippedPixels[index],unclippedPixels[index+1],unclippedPixels[index+2]);
        if(exposed>225 && original<180){
          clipped=true;
          break;
        }
      }
      const horizontalOverflow=Array.from(card.querySelectorAll('p')).some(p=>
        p.scrollWidth>p.clientWidth+1);
      return {number:number.textContent,unit:unit.textContent,numberBottom,unitBottom,
        deltaCssPx:unitBottom-numberBottom,font:getComputedStyle(number).fontFamily,
        boxSizing:getComputedStyle(unit).boxSizing,
        unitPaddingBottom:getComputedStyle(unit).paddingBottom,
        unitMarginBottom:getComputedStyle(unit).marginBottom,
        unitHeight:getComputedStyle(unit).height,
        clipped,horizontalOverflow,geometry};
    });
  }, {dataUrl:'data:image/png;base64,' + png.toString('base64'),
    unclippedUrl:'data:image/png;base64,' + unclipped.toString('base64'), scale});
  writeFileSync(path.join(output, 'evidence.json'), JSON.stringify({ width,height,scale,evidence,errors },null,2));
  assert.deepEqual(errors, []);
  for(const [index,sample] of evidence.entries()){
    assert.equal(sample.boxSizing, 'border-box');
    assert.equal(sample.horizontalOverflow, false);
    const near=(actual,expected)=>assert(Math.abs(actual-expected)<0.1,
      `几何不符: ${actual} != ${expected}`);
    near(sample.geometry.displayHeight,(height-24)*scale);
    near(sample.geometry.mainTopOffset,0);
    near(sample.geometry.mainBottomOffset,0);
    const titleHeight=Math.min(42,Math.max(21,(index<2 ? 2 : 1)*parseFloat(sample.geometry.labelLineHeight)));
    near(sample.geometry.labelHeight,titleHeight*scale);
    assert.equal(sample.geometry.labelWeight,'500');
    near(sample.geometry.groupCenterOffset,0);
    assert.equal(sample.geometry.groupContained,true);
    if(sample.geometry.subtitleHeight){
      near(sample.geometry.subtitleHeight,16*scale);
      near(sample.geometry.subtitleBottomInset,12*scale);
      assert(sample.geometry.subtitleGap>=-0.1);
      assert.equal(sample.geometry.subtitleFont,'12px');
    }
    near(sample.geometry.gap,(index<2 ? 6 : 11)*scale);
    near(sample.geometry.numericAreaHeight,62*scale);
    near(sample.geometry.rowHeight,62*scale);
    near(sample.geometry.rowCenterOffset,0);
    near(sample.geometry.valueHeight,58*scale);
    near(sample.geometry.unitBoxBottomOffset,-10*scale);
    near(sample.geometry.valueUnitGap,2*scale);
    assert.equal(sample.geometry.valueFont,'46px');
    assert.equal(sample.geometry.unitFont,'16px');
    assert.equal(sample.unitHeight,'21px');
    assert.equal(sample.unitMarginBottom,'10px');
    assert.equal(sample.unitPaddingBottom,'0px');
  }
  const transitions=[];
  for(const index of [0,2]){
    for(const subtitle of ['', null, '左耳', '']){
      await page.evaluate(({index,value})=>window.subtitleUpdaters[index](value),{index,value:subtitle});
      await page.waitForFunction(({index,expected})=>{
        const group=document.querySelector('#card'+index+' [data-node-id="display_subtitle_group"]');
        return expected ? getComputedStyle(group).display!=='none' : getComputedStyle(group).display==='none';
      },{index,expected:Boolean(subtitle)});
      const geometry=await page.evaluate(index=>{
        const card=document.getElementById('card'+index);
        const rect=id=>card.querySelector('[data-node-id="'+id+'"]').getBoundingClientRect();
        const main=rect('display_main_group'),label=rect('display_label'),row=rect('display_value_row');
        const group=card.querySelector('[data-node-id="display_subtitle_group"]');
        const visible=getComputedStyle(group).display!=='none';
        const inset=visible ? card.getBoundingClientRect().bottom-rect('display_secondary').bottom : null;
        const display=rect('display');
        return {visible,mainTopOffset:main.top-display.top,
          mainBottomOffset:main.bottom-(visible ? rect('display_secondary').top : display.bottom),centerOffset:(label.top+row.bottom-main.top-main.bottom)/2,subtitleBottomInset:inset,
          titleGap:row.top-label.bottom,subtitleGap:visible ? rect('display_secondary').top-row.bottom : null};
      },index);
      assert.equal(geometry.visible,Boolean(subtitle));
      assert(Math.abs(geometry.mainTopOffset)<0.1);
      assert(Math.abs(geometry.mainBottomOffset)<0.1);
      assert(Math.abs(geometry.centerOffset)<0.1);
      assert(Math.abs(geometry.titleGap-(index===0 ? 6 : 11)*scale)<0.1);
      if(subtitle) assert(Math.abs(geometry.subtitleBottomInset-12*scale)<0.1);
      transitions.push({index,...geometry});
    }
  }
  const titleTransitions=[];
  for(const subtitle of ['', '2027年5月1日']){
    await page.evaluate(value=>window.subtitleUpdaters[0](value),subtitle);
    for(const title of ['运动会还剩','距离举行第三届运动会还剩','运动会还剩']){
      await page.evaluate(value=>window.titleUpdaters[0](value),title);
      await page.waitForFunction(value=>document.querySelector('#card0 [data-node-id="display_label"]').textContent===value,title);
      const geometry=await page.evaluate(()=>{
        const card=document.getElementById('card0');
        const rect=id=>card.querySelector('[data-node-id="'+id+'"]').getBoundingClientRect();
        const label=rect('display_label'),row=rect('display_value_row'),main=rect('display_main_group');
        const footer=card.querySelector('[data-node-id="display_subtitle_group"]');
        const visible=getComputedStyle(footer).display!=='none';
        const display=rect('display');
        return {mainTopOffset:main.top-display.top,
          mainBottomOffset:main.bottom-(visible ? rect('display_secondary').top : display.bottom),
          title:card.querySelector('[data-node-id="display_label"]').textContent,
          gap:row.top-label.bottom,center:(label.top+row.bottom-main.top-main.bottom)/2,
          contained:label.top>=main.top-0.1 && row.bottom<=main.bottom+0.1,
          visible,bottomInset:visible ? card.getBoundingClientRect().bottom-rect('display_secondary').bottom : null};
      });
      assert.equal(geometry.visible,Boolean(subtitle));
      assert(Math.abs(geometry.mainTopOffset)<0.1);
      assert(Math.abs(geometry.mainBottomOffset)<0.1);
      assert.equal(geometry.contained,true);
      assert(Math.abs(geometry.center)<0.1);
      assert(Math.abs(geometry.gap-(title==='运动会还剩' ? 11 : 6)*scale)<0.1);
      if(subtitle) assert(Math.abs(geometry.bottomInset-12*scale)<0.1);
      titleTransitions.push(geometry);
    }
  }
  writeFileSync(path.join(output,'evidence.json'),JSON.stringify({width,height,scale,evidence,transitions,titleTransitions,errors},null,2));

  assert.deepEqual(errors, [], '动态更新不得产生运行时异常');
  const clippedSamples=evidence.filter(sample=>sample.clipped).map(sample=>sample.number);
  console.log(JSON.stringify({geometryPassed:evidence.length,transitions:transitions.length,titleTransitions:titleTransitions.length,
    clippedSamples,width,height,scale}));
  assert.deepEqual(clippedSamples,[], '固定62/58vp及10vp单位补偿下不得出现可见字形裁切');
} finally {
  await browser.close();
}
