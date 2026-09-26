# Univer UI · Presets · Framework Adapters · Examples

조사 기준: `/Users/yeonwoosung/Desktop/univer` (Apache 2.0, `@univerjs/*` **1.0.2**). Univer를 변경하지 않는다.

이 문서는 브라우저 워크벤치가 어떻게 붙는지, 프리셋이 어떤 플러그인을 묶는지, 플러그인 모드 / 프리셋 모드 / 헤드리스가 어디서 갈라지는지를 고정한다. 원본 근거는 `file:line`으로 적는다.

---

## 1. 한 줄 요약

Univer UI는 React 18 워크벤치다. `@univerjs/design`이 토큰·컴포넌트·CSS를 주고, `@univerjs/ui`의 `UniverUIPlugin`이 컨테이너(리본·슬롯·다이얼로그·클립보드)를 띄우며, Sheets/Docs/Slides UI 플러그인이 `IUIPartsService` 슬롯에 부품을 꽂는다. Vue 3 / Web Component는 그 컨테이너 위에서 컴포넌트 핸들러만 바꾼다.

앱을 띄우는 방법은 세 가지다.

| 모드 | 엔트리 | 언제 |
| --- | --- | --- |
| **Plugin Mode** | `new Univer()` + `registerPlugin` + 패키지별 CSS/locale/facade import | 패키지·레이지 로딩·커스텀 런타임을 직접 조합할 때. 이 레포 `examples/`의 Slides가 이 경로다. |
| **Preset Mode** | `createUniver({ presets })` (`presets/src/preset.ts`) | Sheets/Docs(브라우저) 또는 Node 코어를 빠르게 붙일 때. Sheets·Docs 워크벤치가 이 경로다. |
| **Headless** | UI/렌더 엔진 없이 모델·커맨드·수식만. Node 프리셋 또는 Plugin Mode에서 UI 패키지를 빼는 구성 | 서버 처리, 에이전트, 자동화. README가 말하는 “Headless for AI infrastructure”. |

근거: `README.md:123-129`, `README.md:143-145`, `README.md:268-274`, `docs/ISOMORPHIC.md:11-18`.

`examples/`는 기능별 데모 파일이 아니라 Vite 워크벤치 하나다. 해시 `#sheets|#docs|#slides`, 기본 `#sheets`. Sheets/Docs는 Preset, Slides는 Plugin Mode. 시트 fixture는 11개 탭(core, CF, DV, drawing, filter, find-replace, hyper-link, note, sort, table, thread-comment). 콘솔 `window.univer` / `window.univerAPI`. 로케일은 JSON이 아니라 `src/locale/*.ts` 19종. 커스텀 메뉴는 `univerAPI.createMenu(...).appendTo('ribbon.start.others')`. 상세는 [13-runtime-contracts.md](./13-runtime-contracts.md) §8·§11·§12.

---

## 2. Plugin Mode vs Preset Mode vs Headless

README는 세 모드를 표로 고정한다 (`README.md:268-274`).

| Choose | When | Start here |
| --- | --- | --- |
| Plugin Mode | 패키지, 의존성, 레이지 로딩, 커스텀 런타임을 엄격히 통제 | `examples/` + architecture guide |
| Preset Mode | Sheets / Docs / Node를 최소 설정으로 | `presets/` |
| Headless Mode | 서버 워크북/문서 처리, 수식, UI 없는 자동화 | Headless Univer 가이드 |

### 2.1 Plugin Mode (README 퀵스타트)

플러그인 모드는 패키지, 스타일, locale merge, Facade 등록, 플러그인 config를 호출부가 모두 적는다 (`README.md:147-223`).

필수 패턴:

1. `@univerjs/core`, `design`, `docs`, `docs-ui`, `engine-formula`, `engine-render`, `sheets`, `sheets-formula`, `sheets-formula-ui`, `sheets-numfmt`, `sheets-numfmt-ui`, `sheets-ui`, `ui`를 같은 버전으로 설치.
2. `mergeLocales(DesignEnUS, UIEnUS, DocsUIEnUS, SheetsEnUS, …)`로 locale 맵을 만든다.
3. CSS를 패키지별로 `import '@univerjs/design/lib/index.css'` 형태로 넣는다.
4. Facade side-effect: `import '@univerjs/ui/facade'` 등.
5. `new Univer({ locale, locales })` 후 `registerPlugin`. **UI는 `UniverUIPlugin`에 `{ container: 'app' }`를 넘긴다.**
6. `FUniver.newAPI(univer)`로 Facade를 감싼다.

컨테이너 HTML은 `<div id="app" style="height: 100vh"></div>` (`README.md:260-264`).

### 2.2 Preset Mode

프리셋은 “플러그인 묶음 + Facade side-effect + (브라우저면) CSS 번들 + locales 엔트리”다 (`README.md:228-256`).

```ts
const { univerAPI } = createUniver({
  locale: LocaleType.EN_US,
  locales: {
    [LocaleType.EN_US]: mergeLocales(UniverPresetSheetsCoreEnUS),
  },
  presets: [
    UniverSheetsCorePreset({ container: 'app' }),
  ],
})
univerAPI.createWorkbook({})
```

CSS는 프리셋 한 줄: `import '@univerjs/preset-sheets-core/lib/index.css'`.

### 2.3 Headless

동형 설계의 규칙 (`docs/ISOMORPHIC.md:11-18`): 기능은 **로직 플러그인**과 **UI 플러그인**으로 나눈다. 필터는 `sheets-filter` / `sheets-filter-ui`가 그 예다. Facade는 브라우저와 Node 모두에서 쓰이므로 로직 플러그인에 둔다 (`docs/ISOMORPHIC.md:23-30`).

헤드리스 프리셋은 UI·렌더 엔진·CSS를 넣지 않는다.

- `@univerjs/preset-sheets-node-core` README: CSS **No**, Locales **Yes**, Facade **Yes**.
- `@univerjs/preset-docs-node-core` README: CSS **No**, Locales **Yes**, Facade **Yes**.

Node.js 런타임은 `>=18.17.0` (`README.md:286`).

실제 `createUniver`는 헤드리스 전용 분기가 없다. UI를 빼는 것은 **넣는 프리셋/플러그인의 집합**으로 결정된다. `UniverSheetsNodeCorePreset`은 `UniverUIPlugin` / `UniverRenderEnginePlugin`을 등록하지 않는다 (`presets/packages/preset-sheets-node-core/src/preset.ts:64-96`).

---

## 3. UI 스택: design · ui · themes

세 패키지가 뷰 레이어의 바닥이다. 버전은 모두 `1.0.2`.

| 패키지 | 역할 | CSS | Locales | Facade | UMD |
| --- | --- | :---: | :---: | :---: | --- |
| `@univerjs/design` | React 디자인 시스템, 토큰, `ConfigProvider`, `render`/`unmount` | Yes | Yes (`./locale/*`) | No | `UniverDesign` |
| `@univerjs/ui` | 워크벤치, 메뉴, 다이얼로그, 클립보드, Facade UI | Yes | Yes (`./locale/*`) | Yes (`./facade`) | `UniverUi` |
| `@univerjs/themes` | 내장 테마 객체 (CSS 파일 없음) | No | No | No | `UniverThemes` |

### 3.1 `@univerjs/design`

`packages/design/src/index.ts:18`이 `import './global.css'`를 한다. 소스에서 패키지를 import하면 Tailwind 유틸이 따라온다. 배포본은 `import '@univerjs/design/lib/index.css'` (`packages/design/README.md:27-30`).

`global.css`는 Tailwind 지시어만 있다 (`packages/design/src/global.css:1-3`):

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

컴포넌트는 Radix + CVA + Tailwind다. `packages/design/src/index.ts`가 내보내는 것:

Accordion, ActionRow, Avatar, Badge, Button/ButtonGroup/StateIconButton, Calendar, CascaderList, Checkbox/CheckboxGroup, ColorPicker 계열, Command, **ConfigProvider**, Confirm/MobileConfirm, DatePicker/DateRangePicker, Dialog/MobileDialog, DraggableList, Dropdown/DropdownMenu 모바일 포함, FormLayout, Gallery, GradientColorPicker, HoverCard, Input/InputNumber, KBD, Message, MobileActionRow, Pager, Panel, Popup, Radio/RadioGroup, Segmented, Select/MultipleSelect/SelectList, Separator, Switch, Textarea, TimeInput, Toaster, Tooltip, Tree, VirtualList, 그리고 `clsx` / `render` / `unmount`.

워크벤치가 테마·locale·방향을 주입하는 지점은 `ConfigProvider`다 (`packages/design/src/components/config-provider/ConfigProvider.tsx:41-59`). `locale`은 `locale.design` 서브트리를 기대하고, `DirectionProvider`로 LTR/RTL을 건다. `mountContainer`는 포탈 루트다.

디자인 locale 키 루트는 `design`이다 (`packages/design/src/locale/en-US.ts:17-18`). Accessibility, Confirm, CascaderList, Calendar 등.

지원 locale 파일은 UI와 동일 세트다: `ar-SA`, `ca-ES`, `de-DE`, `en-US`, `es-ES`, `fa-IR`, `fr-FR`, `id-ID`, `it-IT`, `ja-JP`, `ko-KR`, `pl-PL`, `pt-BR`, `ru-RU`, `sk-SK`, `vi-VN`, `zh-CN`, `zh-HK`, `zh-TW`.

React peer: `^16.9 \|\| ^17 \|\| ^18 \|\| ^19` (`packages/design/package.json:73-76`). README 호환 표는 React 18 기준, 16.9+/17은 최소 호환 (`README.md:285`).

### 3.2 `@univerjs/ui`

공유 애플리케이션 UI 프레임워크 (`packages/ui/README.md:7`). 내보내는 플러그인 클래스:

- `UniverUIPlugin` — 데스크톱 워크벤치 (`packages/ui/src/plugin.ts:91-191`)
- `UniverMobileUIPlugin` — 모바일 워크벤치 (`packages/ui/src/mobile-plugin.ts:88`)

둘 다 `@DependentOn(UniverRenderEnginePlugin)`이다. 렌더 엔진 없이 UI를 올리면 의존성 검사가 실패한다.

`packages/ui/src/index.ts:18`도 `import './global.css'`다. UI CSS는 `@tailwind components/utilities`만 쓰고 base는 design에 맡긴다 (`packages/ui/src/global.css:1-6`).

설정 키는 `ui.config` (`packages/ui/src/config/config.ts:21-41`).

```ts
export interface IUniverUIConfig extends IWorkbenchOptions {
    disableAutoFocus?: true;
    override?: DependencyOverride;
    menu?: MenuConfig;
    popupRootId?: string;
    avatarFallback?: string;
}
```

`IWorkbenchOptions` (`packages/ui/src/controllers/ui/ui.controller.ts:22-62`):

| 필드 | 의미 |
| --- | --- |
| `container` | `string` id 또는 `HTMLElement`. 없으면 id `univer`인 div를 만든다. |
| `header` / `toolbar` / `footer` / `headerMenu` / `contextMenu` | 크롬 가시성 |
| `ribbonType` | `'collapsed' \| 'simple' \| 'classic' \| 'grid'` |
| `customFontFamily` | FontService에 넣을 폰트 목록 |

플러그인 생성자 (`packages/ui/src/plugin.ts:106-120`)는 `popupRootId`를 `univer-popup-portal-${random}`으로 기본 설정하고, `disableAutoFocus`면 컨텍스트 키 `DISABLE_AUTO_FOCUS`를 켠다. `menu`는 `IConfigService.setConfig('menu', menu, { merge: true })`.

`onStarting`이 등록하는 핵심 의존성 (`packages/ui/src/plugin.ts:123-175`):

- `ComponentManager`, `IconManager`, `ZIndexManager`
- `IUIPartsService` → `UIPartsService` (슬롯 레지스트리)
- `IWorkbenchService` → `WorkbenchService`
- `ILayoutService`, `IRibbonService`, `IMenuManagerService`, `IShortcutService`
- 클립보드 / 알림 / 갤러리 / 다이얼로그 / 컨펌 / 사이드바 / 메시지 / 로컬파일
- `ThemeSwitcherService`
- `IUIController` 팩토리 → `DesktopUIController(this._config)`

`touchDependencies`로 `ComponentsController`, `IUIController`, `ErrorController`를 즉시 기동한다. 그래서 `registerPlugin(UniverUIPlugin, { container })` 시점에 워크벤치가 마운트된다.

모바일 플러그인은 같은 슬롯 서비스에 `MobileUIController` / `MobileConfirmService` / `MobileDialogService`를 넣는다 (`packages/ui/src/mobile-plugin.ts:88-99`).

### 3.3 `@univerjs/themes`

테마는 JS 객체다. CSS 변수를 직접 배포하지 않는다. 워크벤치가 `ThemeSwitcherService.injectThemeToHead`로 `:root { --univer-… }`를 주입한다.

export (`packages/themes/src/index.ts:17-24`):

| export | 파일 |
| --- | --- |
| `defaultTheme` / `blueTheme` (동일) | `default.ts` |
| `darkBlueTheme` | `dark-blue.ts` |
| `greenTheme` | `green.ts` |
| `orangeTheme` | `orange.ts` |
| `purpleTheme` | `purple.ts` |
| `redTheme` | `red.ts` |
| `yellowTheme` | `yellow.ts` |

`Theme` 타입은 `typeof defaultTheme` (`packages/themes/src/default.ts:188`). 팔레트 키: `primary`, `gray`, `blue`, `red`, `orange`, `yellow`, `green`, `jiqing`, `indigo`, `purple`, `pink`, `loop-color`, `highlight.background`. 각 색은 50–900 (gray는 0·1000 포함).

`IUniverConfig.theme` / `darkMode`가 인스턴스 생성 시 `ThemeService`로 들어간다 (`packages/core/src/univer.ts:63-73`). 워크벤치는 `themeService.currentTheme$`를 구독해 CSS 변수를 다시 쓴다 (`packages/ui/src/views/workbench/Workbench.tsx:100-117`). `darkMode`면 `document.documentElement`에 `univer-dark` 클래스를 단다.

`ThemeSwitcherService` (`packages/ui/src/services/theme-switcher/theme-switcher.service.ts:20-55`)는 id `univer-theme-css-variables`인 `<style>`을 `document.head`에 넣고, 객체를 `--univer-primary-600` 형태의 변수로 flatten한다.

---

## 4. UniverUIPlugin 컨테이너에 UI 플러그인이 붙는 방식

핵심 계약: **피처 UI는 자기 DOM 트리를 만들지 않는다.** `IUIPartsService.registerComponent(BuiltInUIPart.*, factory)`로 슬롯에 React 컴포넌트를 등록하고, 워크벤치가 그 슬롯을 렌더한다.

### 4.1 슬롯 키

`packages/ui/src/services/parts/parts.service.ts:26-40`:

```ts
export enum BuiltInUIPart {
    GLOBAL = 'global',
    HEADER = 'header',
    HEADER_MENU = 'header-menu',
    CONTENT = 'content',
    FOOTER = 'footer',
    LEFT_SIDEBAR = 'left-sidebar',
    FLOATING = 'floating',
    UNIT = 'unit',
    CUSTOM_HEADER = 'custom-header',
    CUSTOM_LEFT = 'custom-left',
    CUSTOM_RIGHT = 'custom-right',
    CUSTOM_FOOTER = 'custom-footer',
    TOOLBAR = 'toolbar',
}
```

`registerComponent`는 파트당 `Set`에 팩토리 결과를 넣고 `componentRegistered$`를 방출한다 (`packages/ui/src/services/parts/parts.service.ts:128-144`). `setUIVisible` / `registerDisabledUIParts`로 가시성을 끈다. Facade는 `univerAPI.setUIVisible(BuiltInUIPart.HEADER, false)` (`packages/ui/src/facade/f-univer.ts:368-388`, mixin `563-566`).

### 4.2 부트스트랩 순서

```
registerPlugin(UniverUIPlugin, { container })
  → constructor: ui.config 저장
  → onStarting: DesktopUIController 생성
      → menuManagerService.mergeMenu(menuSchema)
      → 내장 슬롯 등록 (FLOATING / CONTENT / TOOLBAR)
      → bootstrap(container)
          → mountDesktopWorkbench → React render(DesktopWorkbench, mountContainer)
          → onRendered(contentElement)
              → layoutService.registerRootContainerElement / registerContentElement
              → Ready 이후 canvas를 contentElement에 engine.mount
```

컨테이너 해석 (`packages/ui/src/controllers/ui/ui-desktop.controller.ts:68-110`):

1. `container`가 문자열이면 `document.getElementById`. 없으면 그 id로 div를 만든다.
2. `HTMLElement`면 그대로 쓴다.
3. 둘 다 아니면 id `univer`인 div를 만든다. **이 div는 document에 append되지 않는다** — 호출부가 붙여야 한다.
4. dispose 시 `@univerjs/design`의 `unmount(mountContainer)`.

내장 부품 (`packages/ui/src/controllers/ui/ui-desktop.controller.ts:61-65`):

| 슬롯 | 컴포넌트 |
| --- | --- |
| `FLOATING` | `CanvasPopup` |
| `CONTENT` | `FloatDom` (캔버스 위 HTML 오버레이) |
| `TOOLBAR` | `Ribbon` |

모바일은 `CONTENT`에 CanvasPopup+FloatDom, `TOOLBAR`에 `MobileRibbon` (`packages/ui/src/controllers/ui/ui-mobile.controller.ts:61-63`).

### 4.3 DesktopWorkbench 레이아웃

`packages/ui/src/views/workbench/Workbench.tsx:66-259`. `useComponentsOfPart`로 슬롯을 구독하고 `ComponentContainer`가 Set을 렌더한다 (`packages/ui/src/views/components/ComponentContainer.tsx:31-37`, `48-68`).

DOM 구조 (위에서 아래):

1. `CUSTOM_HEADER`
2. `header && toolbar`이면 `<header>` 안에 `TOOLBAR` (sharedProps: `ribbonType`, `headerMenuComponents`, `headerMenu`)
3. 그리드: `LEFT_SIDEBAR` | (`HEADER` + **CONTENT** canvas host) | 하드코딩 `Sidebar` (ISidebarService)
4. `footer`이면 `FOOTER`
5. 포탈 영역: `GLOBAL`, `DesktopContextMenu`, `FLOATING` 포탈, `#popupRootId`

`contentRef`가 캔버스 호스트다 (`Workbench.tsx:220-229`). Ready 이후 `onRendered(contentRef.current)` (`Workbench.tsx:119-123`).

`ConfigProvider locale={locale?.design}` — 즉 Univer locale 팩의 `design` 키가 디자인 시스템에 전달된다 (`Workbench.tsx:149`).

### 4.4 캔버스가 CONTENT에 붙는 경로

`SingleUnitUIController._bootstrapWorkbench` (`packages/ui/src/controllers/ui/ui-shared.controller.ts:57-107`):

1. workbench `onRendered`에서 루트/콘텐츠 엘리먼트를 LayoutService에 등록.
2. `LifecycleStages.Ready`를 기다린 뒤 300ms 후 첫 렌더.
3. `IRenderManagerService.getRenderAll()`에서 메인 씬을 찾아 `renderer.engine.mount(contentElement)`.
4. `focused$` / `created$`로 유닛이 바뀌면 이전 엔진 `unmount` 후 새 엔진 `mount`.
5. 내부 에디터 id (`isInternalEditorID`)와 `isMainScene === false`는 건너뛴다.
6. `LifecycleStages.Rendered` → 3초 후 `Steady`.

즉 **Sheets/Docs/Slides 캔버스는 UniverUIPlugin이 만든 CONTENT div의 자식**이다. 피처 UI 플러그인은 같은 CONTENT 슬롯에 오버레이(시트 그리드 주변 UI, 문서 사이드 메뉴, 슬라이드 에디터 컨테이너)를 추가로 등록한다.

### 4.5 제품 UI가 꽂는 슬롯

| 플러그인 | 슬롯 | 컴포넌트 | 근거 |
| --- | --- | --- | --- |
| `UniverSheetsUIPlugin` | HEADER / FOOTER / CONTENT | `RenderSheetHeader` / `RenderSheetFooter` / `RenderSheetContent` | `packages/sheets-ui/src/controllers/ui.controller.ts:344-351` |
| Sheets mobile | HEADER / CONTENT / FOOTER×2 | MobileSheetBar, MobileRenderSheetContent, MobileFormulaBar, MobileSheetActionPanel | `packages/sheets-ui/src/controllers/mobile/ui-mobile.controller.ts:317-320` |
| `UniverDocsUIPlugin` | FOOTER / CONTENT | `DocFooter` / `DocSideMenu` | `packages/docs-ui/src/controllers/ui.controller.ts:82-85` |
| `UniverSlidesUIPlugin` | LEFT_SIDEBAR / CONTENT | `SlideSideBar` / `SlideEditorContainer` | `packages/slides-ui/src/controllers/ui.controller.ts:84-91` |
| `UniverSheetsFormulaUIPlugin` | GLOBAL | `GlobalRangeSelector` | `packages/sheets-formula-ui/src/plugin.ts:140` |
| Dialog/Confirm/Message/Notification/Gallery | GLOBAL | 각 Part | `packages/ui/src/services/dialog/desktop-dialog.service.ts:91` 등 |

`DependentOn`은 UI 플러그인을 직접 가리키지 않는 경우가 많다.

- `UniverDocsUIPlugin`: `UniverDocsPlugin`, `UniverRenderEnginePlugin` (`packages/docs-ui/src/plugin.ts:256`)
- `UniverSheetsUIPlugin`: Docs + Formula + Render + Sheets + **DocsUI** (`packages/sheets-ui/src/plugin.ts:130-136`)
- `UniverSlidesUIPlugin`: Docs + Drawing + Render + Slides + DocsUI (`packages/slides-ui/src/plugin.ts:50-56`)

그래도 생성자에서 `ILayoutService` / `IMenuManagerService` / `IUIPartsService` / `IShortcutService`를 `@univerjs/ui`에서 주입한다. **`UniverUIPlugin`(또는 Mobile)이 먼저 등록되어 있어야** 슬롯 서비스가 존재한다. 프리셋은 그 순서를 플러그인 배열로 고정한다.

메뉴는 `IMenuManagerService.mergeMenu(schema)`로 리본/컨텍스트 메뉴에 합쳐진다. Docs UI는 `appendRootMenu(floatToolbarMenuSchema)`도 한다 (`packages/docs-ui/src/controllers/ui.controller.ts:87-90`).

### 4.6 ComponentManager (이름 있는 컴포넌트)

슬롯과 별도로, 메뉴 아이콘·플로트 DOM·커스텀 팝업은 `ComponentManager.register(name, component, { framework })`다 (`packages/ui/src/common/component-manager.ts:43-62`). 기본 `framework`는 `'react'`. `'vue3'`인데 핸들러가 없으면 v0.9.0 이후 `@univerjs/ui-adapter-vue3`를 설치하라는 에러를 던진다 (`component-manager.ts:46-48`).

`ComponentsController`가 부트 시 ColorPicker, FontFamily, FontSize, EmojiPicker, ShortcutPanel, ObjectPermission 등을 등록한다 (`packages/ui/src/controllers/components.controller.ts:55-63`).

Facade (`packages/ui/src/facade/f-univer.ts:414-457`):

- `registerComponent(name, component, options?)`
- `registerUIPart(BuiltInUIPart, component)`
- `getComponentManager()`
- `createMenu` / `createSubmenu` / `updateMenuConfig`
- `openSidebar` / `openDialog` / `showMessage`
- `setRibbonType` / `setUIVisible` / `addFonts`

`import '@univerjs/ui/facade'`가 `FUniver`에 이 mixin을 붙인다 (`packages/ui/src/facade/index.ts:17-19`). `FEnum.BuiltInUIPart` / `KeyCode`도 여기서 확장된다 (`packages/ui/src/facade/f-enum.ts:38-48`).

---

## 5. Framework adapters

뷰 레이어는 React다. Vue 3 / Web Component는 `ComponentManager.setHandler`로 **이름 있는 컴포넌트**만 감싼다. 워크벤치 셸 자체를 Vue로 바꾸지 않는다.

둘 다 CSS·locales·Facade가 없다 (`packages/ui-adapter-vue3/README.md:11-13`, `packages/ui-adapter-web-component/README.md:11-13`). `UniverUIPlugin`이 `ComponentManager`를 등록한 뒤에 어댑터를 `registerPlugin`해야 한다 — 생성자가 `ComponentManager`를 주입한다.

### 5.1 `@univerjs/ui-adapter-vue3`

클래스 `UniverVue3AdapterPlugin`, `pluginName = 'UNIVER_UI_ADAPTER_VUE3_PLUGIN'` (`packages/ui-adapter-vue3/src/plugin.ts:30-32`). peer `vue >= 3`.

`onStarting` (`plugin.ts:51-66`):

```ts
this._componentManager.setHandler('vue3', (component) => {
    return (props) => createElement(VueComponentWrapper, {
        component,
        props: /* key 제외 */,
        reactUtils: { createElement, useEffect, useRef },
    });
});
```

`VueComponentWrapper`는 빈 div를 만들고 `vue`의 `h` + `render(vnode, dom)`으로 마운트한다. cleanup은 `render(null, dom)` (`plugin.ts:79-91`).

사용: `univerAPI.registerComponent('my-comp', VueComponent, { framework: 'vue3' })`.

config 키 `ui-adapter-vue3.config`, 인터페이스는 빈 객체 (`packages/ui-adapter-vue3/src/config/config.ts:17-23`).

### 5.2 `@univerjs/ui-adapter-web-component`

클래스 `UniverWebComponentAdapterPlugin`, `pluginName = 'UNIVER_UI_ADAPTER_WEB_COMPONENT_PLUGIN'` (`packages/ui-adapter-web-component/src/plugin.ts:28-31`).

핸들러 이름 `'web-component'`. **커스텀 엘리먼트 태그 이름이 필요하다** — wrapper가 `name` 없으면 throw (`plugin.ts:77-79`). `customElements.define(name, component)` 후 엘리먼트를 만들고, `key`를 제외한 props를 **DOM property**로 할당한다 (`plugin.ts:90-96`). 객체 값(`data`, `extraProps`)이 attribute가 아니라 property로 들어가는 이유다 (README:33).

```ts
univerAPI.registerComponent('my-popup', MyPopup, { framework: 'web-component' });
```

config 키 `ui-adapter-web-component.config` (`packages/ui-adapter-web-component/src/config/config.ts:17-23`).

---

## 6. 프리셋 전체 표

`presets/packages/` 아래 **17개**. Slides 프리셋은 없다. 브라우저 코어 2 + Node 코어 2 + Sheets 애드온 10 + Docs 애드온 3.

README 패키지 개요의 CSS / Locales / Facade는 각 preset README 표를 따른다.

| 패키지 | 런타임 | CSS | Locales | Facade | Worker 엔트리 | 팩토리 | 넣는 플러그인 |
| --- | --- | :---: | :---: | :---: | :---: | --- | --- |
| `@univerjs/preset-sheets-core` | **browser** | Yes | Yes | Yes | `./worker` → `UniverSheetsCoreWorkerPreset` | `UniverSheetsCorePreset` | Network, Docs, RenderEngine, **UI**, DocsUI, (optional RPCMainThread), FormulaEngine, Sheets, SheetsUI, Numfmt, NumfmtUI, SheetsFormula, SheetsFormulaUI |
| `@univerjs/preset-sheets-node-core` | **node-core** | No | Yes | Yes | `./worker` → `UniverSheetsNodeCoreWorkerPreset` | `UniverSheetsNodeCorePreset` | (optional RPCNodeMain), FormulaEngine, ThreadComment, Docs, Sheets, SheetsFormula, DataValidation, Filter, HyperLink, Drawing, Sort, ThreadComment. **UI/Render 없음** |
| `@univerjs/preset-docs-core` | **browser** | Yes | Yes | Yes | 없음 | `UniverDocsCorePreset` | Network, Docs, RenderEngine, **UI**, DocsUI, FormulaEngine |
| `@univerjs/preset-docs-node-core` | **node-core** | No | Yes | Yes | 없음 (RPC 주석 처리) | `UniverDocsNodeCorePreset` | FormulaEngine, ThreadComment, Docs, DocsHyperLink, DocsDrawing. **UI/Render 없음** |
| `@univerjs/preset-sheets-conditional-formatting` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsConditionalFormattingPreset` | SheetsConditionalFormatting + UI |
| `@univerjs/preset-sheets-data-validation` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsDataValidationPreset` | DataValidation, SheetsDataValidation, SheetsDataValidationUI |
| `@univerjs/preset-sheets-drawing` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsDrawingPreset` | Drawing(+collab 시 IImageIoService null), DocsDrawing, DrawingUI, SheetsDrawing, SheetsDrawingUI |
| `@univerjs/preset-sheets-filter` | browser 애드온 | Yes | Yes | Yes | `./worker` → `UniverSheetsFilterWorkerPreset` | `UniverSheetsFilterPreset` | SheetsFilter + FilterUI. 워커는 Filter만 |
| `@univerjs/preset-sheets-find-replace` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsFindReplacePreset` | FindReplace, SheetsFindReplace |
| `@univerjs/preset-sheets-hyper-link` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsHyperLinkPreset` | SheetsHyperLink + UI (`urlHandler`) |
| `@univerjs/preset-sheets-note` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsNotePreset` | SheetsNote + NoteUI |
| `@univerjs/preset-sheets-sort` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsSortPreset` | SheetsSort + SortUI |
| `@univerjs/preset-sheets-table` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsTablePreset` | SheetsTable + TableUI |
| `@univerjs/preset-sheets-thread-comment` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverSheetsThreadCommentPreset` | ThreadCommentUI, SheetsThreadComment, SheetsThreadCommentUI |
| `@univerjs/preset-docs-drawing` | browser 애드온 | Yes | Yes | Yes | 없음 | `UniverDocsDrawingPreset` | Drawing(+collab override), DrawingUI, DocsDrawing, DocsDrawingUI |
| `@univerjs/preset-docs-hyper-link` | browser 애드온 | Yes | Yes | **No** | 없음 | `UniverDocsHyperLinkPreset` | DocsHyperLink + UI |
| `@univerjs/preset-docs-thread-comment` | browser 애드온 | Yes | Yes | **No** | 없음 | `UniverDocsThreadCommentPreset` | ThreadCommentUI, DocsThreadCommentUI |

### 6.1 브라우저 vs node-core

| | browser core | node-core |
| --- | --- | --- |
| `UniverUIPlugin` | 있음. `container` 기본 `'app'` | 없음 |
| `UniverRenderEnginePlugin` | 있음 | 없음 |
| `UniverDocsUIPlugin` / `SheetsUIPlugin` | 있음 | 없음 |
| CSS `lib/index.css` | 의존성 `src/global.css`를 가진 패키지의 빌드 CSS를 이어 붙임 | 빌드가 CSS를 만들지 않음 |
| Facade | UI facade 포함 | 시트/수식/필터 등 로직 facade만 |
| 워커 | 브라우저 `UniverRPCMainThreadPlugin` + worker 프리셋 | Node `UniverRPCNodeMainPlugin` + `UniverRPCNodeWorkerPlugin` |
| 기본 기능 범위 | 편집 UI에 필요한 최소 (Sheets는 수식·숫자서식까지) | Sheets node-core는 DV/filter/hyperlink/drawing/sort/comment를 **코어에 포함** |

Sheets 브라우저 코어는 Docs 플러그인까지 넣는다. 시트 셀 에디터가 문서 모델을 쓰기 때문이다 (`presets/packages/preset-sheets-core/src/preset.ts:111-126`). Node 시트 코어도 `UniverDocsPlugin`을 넣지만 Docs UI는 없다 (`preset-sheets-node-core/src/preset.ts:79-80`).

### 6.2 Sheets 브라우저 코어 config

`IUniverSheetsCorePresetConfig` (`preset-sheets-core/src/preset.ts:58-82`)는 UI에서 `container | header | toolbar | ribbonType | menu | contextMenu | disableAutoFocus | customFontFamily`를, Sheets UI에서 `formulaBar | footer`를 가져온다. `workerURL`이 있으면 수식을 워커로 넘기고 메인 스레드는 `notExecuteFormula: true`.

워커 프리셋 (`preset-sheets-core/src/worker.ts:31-42`): Sheets(수식 mutation만), FormulaEngine, RPCWorkerThread, RemoteSheetsFormula.

### 6.3 Docs 브라우저 코어 config

`IUniverDocsCorePresetConfig` (`preset-docs-core/src/preset.ts:33-37`): UI 크롬 + Docs UI `toc`. `collaboration?: true` 필드는 타입에만 있고 이 파일의 플러그인 배열은 쓰지 않는다. 협업 오버라이드는 `createUniver({ collaboration: true })` 또는 drawing 프리셋의 `collaboration` 플래그 쪽이다.

### 6.4 CSS가 있는 프리셋 vs 없는 프리셋

프리셋 CSS는 런타임 import가 아니라 **빌드 타임 concat**이다 (`common/shared/preset-build/style.ts:9-58`).

1. `package.json` dependencies 중 `@univerjs/*`를 순회.
2. 그 패키지에 `src/global.css`가 있으면 `lib/index.css`를 읽는다. 없으면 스킵. 빌드 CSS가 없으면 throw.
3. 모두 이어 `preset/lib/index.css`로 쓴다.
4. 해당 파일이 하나도 없으면 `lib/index.css`를 삭제한다 → node-core README의 CSS **No**.

호출부는 `import '@univerjs/preset-sheets-core/lib/index.css'` 한 줄이면 된다. Plugin Mode처럼 패키지마다 CSS를 나열하지 않는다.

---

## 7. `createUniver` (`presets/src/preset.ts`)

`@univerjs/presets`는 `createUniver` + `@univerjs/core` + `@univerjs/themes`를 재export한다 (`presets/src/index.ts:17-19`). 개별 프리셋 패키지는 여기의 타입 `IPreset`에 맞춰 플러그인 배열을 반환한다.

타입 (`presets/src/preset.ts:26-46`):

```ts
export type IPresetPlugin = PluginCtor<Plugin> | [PluginCtor<Plugin>, ConstructorParameters<PluginCtor<Plugin>>[0]];

export interface IPreset {
    plugins: IPresetPlugin[];
    locales?: IUniverConfig['locales'];
}

export interface IPresetOptions {
    lazy?: boolean;
}

type CreateUniverOptions = Partial<IUniverConfig> & {
    presets: Array<IPreset | [IPreset, IPresetOptions]>;
    plugins?: IPresetPlugin[];
    override?: DependencyOverride;
    collaboration?: true;
};
```

동작 (`preset.ts:48-104`):

1. `collaboration === true`이면 `override`에 `[IUndoRedoService, null]`, `[IAuthzIoService, null]`, `[IMentionIOService, null]`를 넣는다. 협업 레이어가 대체할 자리를 비운다.
2. `new Univer({ logLevel: LogLevel.WARN, ...univerOptions, override })`. locale/theme/darkMode/direction/locales는 여기서 `IUniverConfig`로 들어간다.
3. 프리셋을 순회하며 `pluginName` → `{ plugin, options }` Map에 넣는다. **같은 `pluginName`이 다시 나오면 지우고 덮어쓴다** (마지막 프리셋 승).
4. `options.plugins`(프리셋 밖 추가 플러그인)는 Map에 이미 있으면 **throw**: `Plugin ${name} already registered by presets or other ways!`
5. Map 순서로 `univer.registerPlugin(plugin, options)`.
6. `FUniver.newAPI(univer)`를 씌워 `{ univer, univerAPI }`를 반환한다.

### 선언만 있고 구현이 안 쓰는 필드

- `IPreset.locales` — 프리셋 객체의 locale을 `createUniver`가 merge하지 않는다. locale은 호출부가 `createUniver({ locales })`로 넘긴다.
- `IPresetOptions.lazy` — `[preset, { lazy }]` 튜플에서 `preset[0]`만 꺼내고 options는 버린다 (`preset.ts:68-71`).

locale 병합은 프리셋 패키지의 `locales/en-US` 엔트리와 호출부의 `mergeLocales`가 담당한다. 아래 §8.

Facade side-effect는 각 `preset.ts` 상단의 `import '@univerjs/…/facade'`가 `createUniver` 호출 전에 모듈 로드로 실행된다. Sheets 코어는 network/sheets/ui/docs-ui/sheets-ui/engine-formula/sheets-formula/sheets-numfmt/sheets-formula-ui facade를 미리 로드한다 (`preset-sheets-core/src/preset.ts:38-46`). Node 시트 코어는 UI facade가 없다 (`preset-sheets-node-core/src/preset.ts:32-40`).

---

## 8. Locale merge

### 8.1 `mergeLocales`

`packages/core/src/shared/locale.ts:46-54`. `Object.assign({}, …locales)` — **얕은 병합**. 인자 하나이고 배열이면 스프레드한다.

Univer 인스턴스는 `IUniverConfig.locales` 맵을 받는다 (`packages/core/src/univer.ts:91-94`):

```ts
locales?: ILocales; // { [locale: string]: ILanguagePack }
```

워크벤치는 `localeService.getLocales()`를 `ConfigProvider`에 넘기고, 그 안의 `design` 키가 디자인 시스템 문자열이다.

런타임 추가는 Facade (`packages/core/src/facade/f-univer.ts:446-462`):

```ts
univerAPI.loadLocales('esES', pack); // localeService.load({ esES: pack })
univerAPI.setLocale('esES');
```

### 8.2 Plugin Mode

호출부가 패키지 locale을 하나씩 merge한다 (`README.md:193-206`):

```ts
locales: {
  [LocaleType.EN_US]: mergeLocales(
    DesignEnUS, UIEnUS, DocsUIEnUS,
    SheetsEnUS, SheetsUIEnUS, SheetsFormulaEnUS, …
  ),
}
```

import 경로: `@univerjs/design/locale/en-US`, `@univerjs/ui/locale/en-US` (`packages/ui/package.json:30`, `packages/design/package.json:30`).

패키지 locale 루트 키는 서로 다르다. design은 `design`, ui는 `ui` (`packages/ui/src/locale/en-US.ts:19-20`). 얕은 merge여도 충돌하지 않는다.

### 8.3 Preset Mode — 생성된 `locales/*`

프리셋 빌드의 `generatePresetLocales` (`common/shared/preset-build/locale.ts:54-97`):

1. `@univerjs/ui/src/locale`에서 `xx-YY.ts` 목록을 발견한다 (`common/shared/locale/index.ts:49-59`). UI가 locale 세트의 소스 오브 트루스다.
2. 프리셋 의존성 중 `locale/` 또는 `locales/`에 그 파일이 있는 패키지만 고른다.
3. `src/locales/${locale}.ts`를 생성한다:

```ts
import univerjsdesign from '@univerjs/design/locale/en-US';
import univerjsui from '@univerjs/ui/locale/en-US';
// …
export default Object.assign({}, univerjsdesign, univerjsui, …);
```

4. export 맵에 `./locales/*`로 붙인다 (`preset-sheets-core/package.json:32`).

호출부:

```ts
import UniverPresetSheetsCoreEnUS from '@univerjs/preset-sheets-core/locales/en-US'
mergeLocales(UniverPresetSheetsCoreEnUS, UniverPresetSheetsFilterEnUS, …)
```

여러 프리셋을 쓰면 **프리셋 locale 팩을 다시 `mergeLocales`** 해야 한다. `createUniver`가 프리셋 locale을 자동 합치지 않는다.

### 8.4 Examples 워크벤치

제품별 locale 모듈이 그 제품이 쓰는 프리셋 locale을 merge한다.

Sheets (`examples/src/sheets/locales/en-US.ts:1-26`):

```ts
mergeLocales(core, drawing, conditionalFormatting, dataValidation, filter,
  findReplace, hyperLink, note, sort, table, threadComment)
```

Docs (`examples/src/docs/locales/en-US.ts:1-12`): core + drawing + hyperLink + threadComment.

Slides는 프리셋이 없으므로 패키지 locale을 직접 merge (`examples/src/slides/locales/en-US.ts:1-12`):

```ts
mergeLocales(design, docsUI, slidesUI, ui)
```

로더는 `virtual:univer-examples-*-locale`이다 (`examples/vite.config.ts:34-49`). 개발은 `/__univer_examples_locale` 엔드포인트 + `mergeLocales(...payload.packs)` (`examples/src/dev-locale-loader.ts:18-39`). 프로덕션은 위 `locales/*.ts`의 static import (`examples/src/sheets/locale-loader.ts:9-32`).

지원 태그 19개: `ar-SA` … `zh-TW` (`examples/vite.config.ts:11-31`). RTL은 `arSA`, `faIR` (`examples/src/workbench-settings.ts:72-92`).

설정 변경 시 `univerAPI.loadLocales` + `setLocale` + `setTheme` + `toggleDarkMode` + `setDirection` (`examples/src/mount-example.ts:77-107`).

---

## 9. CSS imports

세 경로가 있다.

### 9.1 Plugin Mode (배포)

README가 나열하는 순서 (`README.md:179-184`):

```ts
import '@univerjs/design/lib/index.css'
import '@univerjs/ui/lib/index.css'
import '@univerjs/docs-ui/lib/index.css'
import '@univerjs/sheets-ui/lib/index.css'
import '@univerjs/sheets-formula-ui/lib/index.css'
import '@univerjs/sheets-numfmt-ui/lib/index.css'
```

UI가 있는 패키지만 CSS를 가진다. 로직 패키지(`@univerjs/sheets`, `@univerjs/core`)는 CSS가 없다.

### 9.2 Preset Mode (배포)

```ts
import '@univerjs/preset-sheets-core/lib/index.css'
import '@univerjs/preset-sheets-filter/lib/index.css'
// 브라우저 애드온마다 한 줄
```

Node 프리셋은 이 파일이 없다. `sideEffects: ["*.css"]` (`presets/packages/preset-sheets-core/package.json:26-28`, `presets/package.json:25-27`).

### 9.3 모노레포 소스 / examples

패키지 `index.ts`가 `import './global.css'`를 하므로 소스 import만으로 Tailwind가  bundler에 들어간다.

- `packages/design/src/index.ts:18`
- `packages/ui/src/index.ts:18`

examples는 제품별 Tailwind 엔트리로 **콘텐츠 스캔 범위**를 나눈다.

| 파일 | `@config` |
| --- | --- |
| `examples/src/sheets/global.css` | `tailwind.sheets.config.ts` |
| `examples/src/docs/global.css` | `tailwind.docs.config.ts` |
| `examples/src/slides/global.css` | `tailwind.slides.config.ts` |

각 제품 `mount.ts`가 자기 `./global.css`를 import한다 (`examples/src/sheets/mount.ts:22`, `docs/mount.ts:16`, `slides/mount.ts:19`). 셸 CSS는 `examples/src/global.css` (워크벤치 헤더, `#app`, `html.univer-dark`).

배포 앱이 examples처럼 소스 `index.ts`를 쓰지 않으면 `lib/index.css`를 **명시 import**해야 한다. 프리셋/플러그인 JS는 CSS를 자동으로 끌어오지 않는다(빌드된 ESM 기준). 소스 개발에서만 `index.ts`의 `import './global.css'`가 동작한다.

---

## 10. Examples 워크벤치 (`examples/src`)

`pnpm dev`가 Vite 8로 Sheets / Docs / Slides 올인원 워크벤치를 띄운다 (`README.md:365-366`). 엔트리는 `examples/index.html` → `src/main.ts`.

### 10.1 셸

`examples/index.html:10-22`: 헤더 탭 `#sheets` / `#docs` / `#slides`, 설정 마운트 `#workbench-settings`, 호스트 `<main id="app">`.

`main.ts`가 해시로 로더를 고른다 (`examples/src/main.ts:23-66`). 기본 해시는 `#sheets`. `createExampleSwitcher`가 이전 Univer를 dispose하고 새 `mount(host, options)`를 호출한다 (`examples/src/mount-example.ts:179-240`).

워크벤치 설정 (`examples/src/workbench-settings.ts:13-59, 94-123`):

| 키 | 값 |
| --- | --- |
| locale | 19개 (`enUS` … `arSA`) |
| region | `auto` 또는 locale |
| direction | `ltr` / `rtl` |
| theme | `blue` `green` `orange` `purple` `red` `yellow` `dark-blue` → `@univerjs/themes` 객체 |
| darkMode | boolean, `html.univer-dark` |
| ribbonType | `grid` `classic` `collapsed` `simple` |
| uiChrome | `full` / `no-ribbon` / `canvas-only` |
| zoomRatio | 0.5 … 4 |

`uiChrome`은 Facade `setUIVisible`로 HEADER/TOOLBAR/FOOTER/LEFT_SIDEBAR를 켠다 (`mount-example.ts:67-75`). `canvas-only`는 넷 다 false.

설정은 `localStorage` 키 `univer.examples.workbench.settings`.

### 10.2 Sheets — Preset Mode

`examples/src/sheets/mount.ts:50-71`. `createUniver` + 브라우저 시트 프리셋 전부:

```
UniverSheetsCorePreset({ container: host, ribbonType })
UniverSheetsDrawingPreset()
UniverSheetsConditionalFormattingPreset()
UniverSheetsFilterPreset()
UniverSheetsHyperLinkPreset()
UniverSheetsDataValidationPreset()
UniverSheetsFindReplacePreset()
UniverSheetsNotePreset()
UniverSheetsSortPreset()
UniverSheetsTablePreset()
UniverSheetsThreadCommentPreset()
```

`univerAPI.createWorkbook(createSheetFixture(…))`. 줌은 `applyWorkbookZoom`.

### 10.3 Docs — Preset Mode

`examples/src/docs/mount.ts:43-61`:

```
UniverDocsCorePreset({ container: host, ribbonType, toc: true })
UniverDocsDrawingPreset()
UniverDocsHyperLinkPreset()
UniverDocsThreadCommentPreset()
```

추가로 `univer.registerPlugin(UniverDocsLayoutWorkerPlugin, { workerFactory })` — 프리셋 밖 플러그인. `createUniver`의 `plugins` 필드가 아니라 반환된 `univer`에 직접 등록한다. 레이아웃 워커는 프리셋에 없다.

유닛: `univer.createUnit(UNIVER_DOC, createDocumentFixture(…))`.

### 10.4 Slides — Plugin Mode (프리셋 없음)

`examples/src/slides/mount.ts:46-67`:

```ts
const univer = new Univer({ locale, region, locales, theme, darkMode, direction });
univer.registerPlugin(UniverRenderEnginePlugin);
univer.registerPlugin(UniverUIPlugin, { container: host, ribbonType });
univer.registerPlugin(UniverDocsPlugin);
univer.registerPlugin(UniverDocsUIPlugin);
univer.registerPlugin(UniverDrawingPlugin);
univer.registerPlugin(UniverSlidesPlugin);
univer.registerPlugin(UniverSlidesUIPlugin);
const univerAPI = FUniver.newAPI(univer);
```

`createUniver`를 쓰지 않는다. Docs UI가 들어가는 이유는 Slides UI의 `DependentOn`이 `UniverDocsUIPlugin`을 요구하기 때문이다 (`packages/slides-ui/src/plugin.ts:50-56`). 줌은 렌더 유닛 `scene.scale`.

### 10.5 세 제품 공통

| | Sheets | Docs | Slides |
| --- | --- | --- | --- |
| 부트 API | `createUniver` | `createUniver` | `new Univer` + `registerPlugin` |
| 컨테이너 | 프리셋 `container: host` | 프리셋 `container: host` | `UniverUIPlugin` `{ container: host }` |
| CSS | `sheets/global.css` (Tailwind sheets config) | `docs/global.css` | `slides/global.css` |
| Locale | 프리셋 locale merge | 프리셋 locale merge | design+ui+docs-ui+slides-ui |
| Facade UI | 프리셋 side-effect | `import '@univerjs/ui/facade'` | `import '@univerjs/ui/facade'` |
| 유닛 생성 | `createWorkbook` | `createUnit(UNIVER_DOC)` | `createUnit(UNIVER_SLIDE)` |

호스트 `#app`은 `isolation: isolate; flex: 1; min-height: 0` (`examples/src/global.css:202-208`). UI 플러그인이 이 엘리먼트에 워크벤치를 렌더한다.

---

## 11. Neos 이식 시 고정할 점

1. **컨테이너는 `UniverUIPlugin` 하나다.** 피처 UI는 `IUIPartsService` 슬롯에만 등록한다. 별도 React 루트를 만들면 리본·포커스·캔버스 마운트가 깨진다.
2. **Headless는 UI 패키지를 빼는 구성이다.** `createUniver`에 headless 플래그는 없다. `preset-sheets-node-core` / `preset-docs-node-core`가 그 집합이다.
3. **Locale은 호출부가 merge한다.** 프리셋 객체의 `locales` 필드는 무시된다. 프리셋 `locales/xx-YY` + `mergeLocales` + `createUniver({ locales })`.
4. **CSS는 명시 import.** 배포 경로에서는 `lib/index.css`. 소스 경로에서만 패키지 `index.ts`의 `global.css`가 따라온다.
5. **Slides는 아직 프리셋이 없다.** Plugin Mode로 UI+DocsUI+Drawing+SlidesUI를 직접 등록한다.
6. **Vue/Web Component 어댑터는 셸이 아니라 `registerComponent` 핸들러다.** 워크벤치는 React로 남는다.
7. **같은 플러그인을 프리셋끼리 중복하면 마지막이 이긴다. 프리셋과 `plugins:`가 겹치면 throw.** (`presets/src/preset.ts:76-89`)
8. **버전은 `@univerjs/*`를 한 줄로 맞춘다.** 아이콘 패키지만 매니페스트 호환 버전을 쓴다 (`README.md:276`).
