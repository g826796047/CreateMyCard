```cardspec
{
  "title": "天气",
  "description": "天气图标",
  "suggestSize": "2x4",
  "imageDomainWhitelist": [
    "hag-ability-test.obs.cn-north-1.myhuaweicloud.com",
    "lfcontentcenterdev.hwcloudtest.cn",
    "hagres-drcn.dbankcdn.com"
  ]
}
```
```genui
{"version":"v0.9","createSurface":{"surfaceId":"surface_card","catalogId":"ohos.a2ui.extended.catalog.form"}}
{"version":"v0.9","updateComponents":{"surfaceId":"surface_card","root":"root","components":[{"id":"root","component":"Column","children":["title","body"],"styles":{"width":"matchParent","height":"matchParent","padding":12,"backgroundColor":"#FFE5EDFE"},"itemMargin":0},{"id":"title","component":"Row","children":["title_title","title_icon"],"styles":{"width":"matchParent","height":20,"flexShrink":0,"justifyContent":"spaceBetween","alignItems":"center"},"itemMargin":0},{"id":"title_title","component":"Text","content":"天气","styles":{"fontSize":12,"fontWeight":400,"lineHeight":1,"textAlign":"start","maxLines":1,"flexShrink":1,"width":"wrapContent","layoutWeight":1,"constraintSize":{"minWidth":0},"fontColor":"#991F4799"}},{"id":"title_icon","component":"Image","src":"https://hagres-drcn.dbankcdn.com/assets/drop_1.svg?version=1","styles":{"width":20,"height":20,"objectFit":"contain","flexShrink":0,"fillColor":"#FF1F4799"}},{"id":"body","component":"Column","children":["content"],"styles":{"width":"matchParent","layoutWeight":1},"itemMargin":0},{"id":"content","component":"Column","children":["content_main"],"itemMargin":2,"styles":{"alignItems":"start","flexShrink":1,"constraintSize":{"minWidth":0},"width":"matchParent"}},{"id":"content_main","component":"Text","content":"天气","styles":{"height":18,"fontSize":18,"fontWeight":700,"lineHeight":1,"maxLines":1,"flexShrink":1,"width":"matchParent","fontColor":"#FF1F4799","textOverflow":"clip"}}]}}
{"version":"v0.9","updateDataModel":{"surfaceId":"surface_card","path":"/","value":{"ui":{"state":"ready"}}}}
```
```schema
{
  "schemaVersion": "widget-artifact-v2"
}
```
```taskspec
{
  "userQuery": "生成天气卡片",
  "size": "2x4",
  "appVersion": "11.7.7.331",
  "eventCandidates": [],
  "dataModelSchema": {
    "data": {}
  },
  "assetCandidates": [
    {
      "id": "asset.drop_1",
      "src": "resources/base/media/drop_1.svg",
      "description": "样式：双水滴实心图标，默认黑色，图形为左侧较大水滴与右侧较小水滴错位叠放，顶部尖收、底部圆润；适用：湿度数据展示、饮水提醒、天气降雨信息。"
    }
  ]
}
```
```effectivecapabilities
{
  "data": [],
  "event": [],
  "asset": [
    "asset.drop_1"
  ]
}
```
```removedcapabilities
[]
```
```generationplan
{
  "candidateDataBindings": [],
  "candidateEventCandidates": [],
  "candidateAssetIds": [
    "asset.drop_1"
  ]
}
```
```meta
{
  "apiVersion": "v1",
  "taskSpecVersion": "task-spec-v1",
  "cardSpecVersion": "card-spec-v1",
  "dslProtocolVersion": "v0.9",
  "skillVersion": "skill-widget-v1",
  "protocolProfileId": "a2ui-form-rom6.0-v1",
  "capabilityRegistryVersion": "app-11.7.7.300_rom-7.0",
  "artifactSchemaVersion": "widget-artifact-v2",
  "generationMode": "create",
  "artifactId": "91c3f19f-55bd-422f-b1d8-8daa37e2098a",
  "createdAt": 1795402859697
}
```
```request
{
  "locale": "zh-CN",
  "device": {
    "romVersion": "7.0"
  },
  "prdVer": "11.7.7.331",
  "protocolProfileId": "a2ui-form-rom6.0-v1",
  "userQuery": "生成天气卡片",
  "size": "2x4",
  "title": "天气",
  "description": "天气图标",
  "candidateAssetIds": [
    "asset.drop_1"
  ],
  "options": {
    "allowDegradation": true
  }
}
```
