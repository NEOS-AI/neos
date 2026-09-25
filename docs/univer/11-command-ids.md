# Univer 커맨드 / 뮤테이션 / 오퍼레이션 ID 전수

조사 기준: `/Users/yeonwoosung/Desktop/univer` v1.0.2. `__tests__`를 제외한 `packages/**/*.ts(x)`에서 `id`/`COMMAND_ID`/`MUTATION_ID`가 `*.command.*` / `*.mutation.*` / `*.operation.*` 패턴인 문자열을 집계했다.

- 합계 **609** (command 367 / mutation 120 / operation 122)
- 네이밍 규칙: `<namespace>.<type>.<name>` (`packages/core/src/services/command/command.service.ts:67-71`)
- 에이전트가 보통 부르는 것은 COMMAND다. MUTATION은 COMMAND가 오케스트레이션하고, OPERATION은 스냅샷에 안 남는다.
- 의미·인터셉터·권한은 [11-commands-permissions.md](./11-commands-permissions.md).


### `action-recorder.command` (6)

- `action-recorder.command.complete-recording`
- `action-recorder.command.replay-local-records`
- `action-recorder.command.replay-local-records-active`
- `action-recorder.command.replay-local-records-name`
- `action-recorder.command.start-recording`
- `action-recorder.command.stop-recording`

### `action-recorder.operation` (2)

- `action-recorder.operation.close-panel`
- `action-recorder.operation.open-panel`

### `base-ui.operation` (2)

- `base-ui.operation.toggle-fullscreen`
- `base-ui.operation.toggle-shortcut-panel`

### `data-validation.command` (3)

- `data-validation.command.addRuleAndOpen`
- `data-validation.command.clear-quick-rule`
- `data-validation.command.insert-quick-rule`

### `data-validation.mutation` (3)

- `data-validation.mutation.addRule`
- `data-validation.mutation.removeRule`
- `data-validation.mutation.updateRule`

### `data-validation.operation` (3)

- `data-validation.operation.close-validation-panel`
- `data-validation.operation.open-validation-panel`
- `data-validation.operation.toggle-validation-panel`

### `doc.command` (91)

- `doc.command.align-action`
- `doc.command.align-center`
- `doc.command.align-justify`
- `doc.command.align-left`
- `doc.command.align-right`
- `doc.command.apply-format-painter`
- `doc.command.break-line`
- `doc.command.bullet-list`
- `doc.command.change-list-nesting-level`
- `doc.command.change-list-type`
- `doc.command.change-paste-mode`
- `doc.command.check-list`
- `doc.command.close-header-footer`
- `doc.command.copy-current-paragraph`
- `doc.command.create-header-footer`
- `doc.command.cut-current-paragraph`
- `doc.command.delete-current-paragraph`
- `doc.command.delete-custom-block`
- `doc.command.delete-drawing`
- `doc.command.delete-left`
- `doc.command.delete-right`
- `doc.command.delete-section-break`
- `doc.command.delete-table-of-contents`
- `doc.command.delete-text`
- `doc.command.enter`
- `doc.command.group-doc-image`
- `doc.command.h1-heading`
- `doc.command.h2-heading`
- `doc.command.h3-heading`
- `doc.command.h4-heading`
- `doc.command.h5-heading`
- `doc.command.horizontal-line`
- `doc.command.ime-input`
- `doc.command.inner-cut`
- `doc.command.inner-paste`
- `doc.command.insert-bullet-below`
- `doc.command.insert-bullet-list-bellow`
- `doc.command.insert-check-list-bellow`
- `doc.command.insert-column-break`
- `doc.command.insert-custom-range`
- `doc.command.insert-doc-image`
- `doc.command.insert-float-image`
- `doc.command.insert-horizontal-line-bellow`
- `doc.command.insert-order-list-bellow`
- `doc.command.insert-section-break`
- `doc.command.insert-special-character`
- `doc.command.insert-table-of-contents`
- `doc.command.insert-text`
- `doc.command.list-operation`
- `doc.command.menu-insert-shape`
- `doc.command.menu-insert-shape.below`
- `doc.command.merge-two-paragraph`
- `doc.command.move-block`
- `doc.command.move-drawing`
- `doc.command.move-inline-drawing`
- `doc.command.normal-text-heading`
- `doc.command.open-header-footer-panel`
- `doc.command.order-list`
- `doc.command.paste-special`
- `doc.command.quick-heading`
- `doc.command.quick-list`
- `doc.command.remove-doc-image`
- `doc.command.remove-horizontal-line`
- `doc.command.replace-selection`
- `doc.command.replace-text-runs`
- `doc.command.select-all`
- `doc.command.select-word`
- `doc.command.set-default-paragraph-style`
- `doc.command.set-drawing-arrange`
- `doc.command.set-inline-format`
- `doc.command.set-input-style`
- `doc.command.set-name`
- `doc.command.set-paragraph-named-style`
- `doc.command.set-permission`
- `doc.command.set-permissions`
- `doc.command.set-section-header-footer-link`
- `doc.command.set-zoom-ratio`
- `doc.command.subtitle-heading`
- `doc.command.switch-mode`
- `doc.command.title`
- `doc.command.toggle-check-list`
- `doc.command.transform-non-inline-drawing`
- `doc.command.ungroup-doc-image`
- `doc.command.update-doc-drawing-distance`
- `doc.command.update-doc-drawing-wrap-text`
- `doc.command.update-doc-drawing-wrapping-style`
- `doc.command.update-drawing-doc-transform`
- `doc.command.update-paragraph-style`
- `doc.command.update-section`
- `doc.command.update-table-of-contents`
- `doc.command.update-text`

### `doc.mutation` (4)

- `doc.mutation.rename-doc`
- `doc.mutation.rich-text-editing`
- `doc.mutation.set-permission-rule`
- `doc.mutation.set-permission-rules`

### `doc.operation` (14)

- `doc.operation.clear-drawing-transformer`
- `doc.operation.click-hyper-link`
- `doc.operation.create-table`
- `doc.operation.edit-doc-image`
- `doc.operation.insert-table-of-contents`
- `doc.operation.move-cursor`
- `doc.operation.move-selection`
- `doc.operation.open-paragraph-permission`
- `doc.operation.open-permission-panel`
- `doc.operation.open-table-of-contents-dialog`
- `doc.operation.set-selections`
- `doc.operation.set-zoom-ratio`
- `doc.operation.show-hyper-link-edit-popup`
- `doc.operation.toggle-hyper-link-info-popup`

### `docs-thread-comment.mutation` (1)

- `docs-thread-comment.mutation.add-decoration`

### `docs.command` (5)

- `docs.command.add-comment`
- `docs.command.create-text-range-comment`
- `docs.command.delete-comment`
- `docs.command.page-setup`
- `docs.command.replace`

### `docs.mutation` (3)

- `docs.mutation.add-hyper-link`
- `docs.mutation.delete-hyper-link`
- `docs.mutation.update-hyper-link`

### `docs.operation` (7)

- `docs.operation.add-drawing-comment`
- `docs.operation.insert-column-break`
- `docs.operation.insert-section-break`
- `docs.operation.open-page-setting`
- `docs.operation.show-comment-panel`
- `docs.operation.start-add-comment`
- `docs.operation.toggle-comment-panel`

### `drawing.operation` (8)

- `drawing.operation.cancel-drawing-group`
- `drawing.operation.set-drawing-arrange`
- `drawing.operation.set-drawing-arrange-back`
- `drawing.operation.set-drawing-arrange-backward`
- `drawing.operation.set-drawing-arrange-forward`
- `drawing.operation.set-drawing-arrange-front`
- `drawing.operation.set-drawing-group`
- `drawing.operation.set-drawing-selected`

### `formula-ui.operation` (5)

- `formula-ui.operation.change-ref-to-absolute`
- `formula-ui.operation.help-function`
- `formula-ui.operation.insert-function`
- `formula-ui.operation.more-functions`
- `formula-ui.operation.search-function`

### `formula.command` (1)

- `formula.command.insert-function`

### `formula.mutation` (28)

- `formula.mutation.register-function`
- `formula.mutation.remove-defined-name`
- `formula.mutation.remove-feature-calculation`
- `formula.mutation.remove-other-formula`
- `formula.mutation.remove-super-table`
- `formula.mutation.set-array-formula-data`
- `formula.mutation.set-cell-formula-dependency-calculation`
- `formula.mutation.set-cell-formula-dependency-calculation-result`
- `formula.mutation.set-defined-name`
- `formula.mutation.set-feature-calculation`
- `formula.mutation.set-formula-calculation-notification`
- `formula.mutation.set-formula-calculation-result`
- `formula.mutation.set-formula-calculation-start`
- `formula.mutation.set-formula-calculation-stop`
- `formula.mutation.set-formula-data`
- `formula.mutation.set-formula-dependency-calculation`
- `formula.mutation.set-formula-dependency-calculation-result`
- `formula.mutation.set-formula-string-batch-calculation`
- `formula.mutation.set-formula-string-batch-calculation-result`
- `formula.mutation.set-image-formula-data`
- `formula.mutation.set-other-formula`
- `formula.mutation.set-query-formula-dependency`
- `formula.mutation.set-query-formula-dependency-all`
- `formula.mutation.set-query-formula-dependency-all-result`
- `formula.mutation.set-query-formula-dependency-result`
- `formula.mutation.set-super-table`
- `formula.mutation.set-super-table-option`
- `formula.mutation.set-trigger-formula-calculation-start`

### `sheet-permission.operation` (2)

- `sheet-permission.operation.openDialog`
- `sheet-permission.operation.openPanel`

### `sheet.command` (239)

- `sheet.command.add-average-conditional-rule`
- `sheet.command.add-color-scale-conditional-rule`
- `sheet.command.add-conditional-rule`
- `sheet.command.add-data-bar-conditional-rule`
- `sheet.command.add-duplicate-values-conditional-rule`
- `sheet.command.add-icon-set-conditional-rule`
- `sheet.command.add-number-conditional-rule`
- `sheet.command.add-range-protection`
- `sheet.command.add-range-protection-from-context-menu`
- `sheet.command.add-range-protection-from-sheet-bar`
- `sheet.command.add-range-protection-from-toolbar`
- `sheet.command.add-rank-conditional-rule`
- `sheet.command.add-table`
- `sheet.command.add-table-theme`
- `sheet.command.add-text-conditional-rule`
- `sheet.command.add-time-period-conditional-rule`
- `sheet.command.add-uniqueValues-conditional-rule`
- `sheet.command.add-worksheet-background-image`
- `sheet.command.add-worksheet-merge`
- `sheet.command.add-worksheet-merge-all`
- `sheet.command.add-worksheet-merge-horizontal`
- `sheet.command.add-worksheet-merge-vertical`
- `sheet.command.add-worksheet-protection`
- `sheet.command.addDataValidation`
- `sheet.command.apply-format-painter`
- `sheet.command.auto-clear-content`
- `sheet.command.auto-fill`
- `sheet.command.cancel-frozen`
- `sheet.command.change-sheet-protection-from-sheet-bar`
- `sheet.command.change-zoom-ratio`
- `sheet.command.clear-filter-criteria`
- `sheet.command.clear-range-conditional-rule`
- `sheet.command.clear-selection-all`
- `sheet.command.clear-selection-content`
- `sheet.command.clear-selection-format`
- `sheet.command.clear-worksheet-conditional-rule`
- `sheet.command.copy-down`
- `sheet.command.copy-formula-only`
- `sheet.command.copy-right`
- `sheet.command.copy-sheet`
- `sheet.command.delete-conditional-rule`
- `sheet.command.delete-drawing`
- `sheet.command.delete-note`
- `sheet.command.delete-range-move-left-confirm`
- `sheet.command.delete-range-move-up-confirm`
- `sheet.command.delete-range-protection`
- `sheet.command.delete-range-protection-from-context-menu`
- `sheet.command.delete-table`
- `sheet.command.delete-worksheet-background-image`
- `sheet.command.delete-worksheet-protection`
- `sheet.command.delete-worksheet-protection-from-sheet-bar`
- `sheet.command.delta-column-width`
- `sheet.command.delta-row-height`
- `sheet.command.expand-selection`
- `sheet.command.group-sheet-image`
- `sheet.command.hide-col-confirm`
- `sheet.command.hide-row-confirm`
- `sheet.command.insert-cell-image`
- `sheet.command.insert-col-after`
- `sheet.command.insert-col-before`
- `sheet.command.insert-col-by-range`
- `sheet.command.insert-defined-name`
- `sheet.command.insert-float-image`
- `sheet.command.insert-multi-cols-before`
- `sheet.command.insert-multi-cols-right`
- `sheet.command.insert-multi-rows-above`
- `sheet.command.insert-multi-rows-after`
- `sheet.command.insert-range-move-down-confirm`
- `sheet.command.insert-range-move-right-confirm`
- `sheet.command.insert-row-after`
- `sheet.command.insert-row-before`
- `sheet.command.insert-row-by-range`
- `sheet.command.insert-sheet`
- `sheet.command.insert-sheet-image`
- `sheet.command.mobile-formula-bar-break-line`
- `sheet.command.mobile-formula-bar-submit`
- `sheet.command.mobile.numfmt.set`
- `sheet.command.move-conditional-rule`
- `sheet.command.move-drawing`
- `sheet.command.move-range-confirm`
- `sheet.command.move-selection`
- `sheet.command.move-selection-enter-tab`
- `sheet.command.numfmt.add.decimal.command`
- `sheet.command.numfmt.set.currency`
- `sheet.command.numfmt.set.numfmt`
- `sheet.command.numfmt.set.percent`
- `sheet.command.numfmt.subtract.decimal.command`
- `sheet.command.optional-paste`
- `sheet.command.paste-besides-border`
- `sheet.command.paste-col-width`
- `sheet.command.paste-format`
- `sheet.command.paste-formula`
- `sheet.command.paste-value`
- `sheet.command.re-calc-filter`
- `sheet.command.refill`
- `sheet.command.register-worksheet-range-theme-style`
- `sheet.command.remove-all-data-validation`
- `sheet.command.remove-col-by-range`
- `sheet.command.remove-col-confirm`
- `sheet.command.remove-data-validation-rule`
- `sheet.command.remove-defined-name`
- `sheet.command.remove-row-by-range`
- `sheet.command.remove-row-confirm`
- `sheet.command.remove-sheet`
- `sheet.command.remove-sheet-confirm`
- `sheet.command.remove-sheet-filter`
- `sheet.command.remove-sheet-image`
- `sheet.command.remove-table-theme`
- `sheet.command.remove-worksheet-merge`
- `sheet.command.remove-worksheet-range-theme-style`
- `sheet.command.repeat-last-action`
- `sheet.command.replace`
- `sheet.command.reset-background-color`
- `sheet.command.reset-range-text-color`
- `sheet.command.reset-text-color`
- `sheet.command.save-cell-images`
- `sheet.command.scroll-to-cell`
- `sheet.command.scroll-view`
- `sheet.command.scroll-view-reset`
- `sheet.command.select-all`
- `sheet.command.select-range`
- `sheet.command.set-background-color`
- `sheet.command.set-bold`
- `sheet.command.set-border`
- `sheet.command.set-border-basic`
- `sheet.command.set-border-color`
- `sheet.command.set-border-position`
- `sheet.command.set-border-style`
- `sheet.command.set-col-auto-width`
- `sheet.command.set-col-data`
- `sheet.command.set-col-frozen`
- `sheet.command.set-col-header-height`
- `sheet.command.set-col-hidden`
- `sheet.command.set-col-is-auto-width`
- `sheet.command.set-col-visible-on-cols`
- `sheet.command.set-conditional-rule`
- `sheet.command.set-defined-name`
- `sheet.command.set-drawing-arrange`
- `sheet.command.set-drawing-placement`
- `sheet.command.set-filter-criteria`
- `sheet.command.set-filter-range`
- `sheet.command.set-first-column-frozen`
- `sheet.command.set-first-row-frozen`
- `sheet.command.set-font-family`
- `sheet.command.set-font-size`
- `sheet.command.set-frozen`
- `sheet.command.set-gridlines-color`
- `sheet.command.set-horizontal-text-align`
- `sheet.command.set-infinite-format-painter`
- `sheet.command.set-italic`
- `sheet.command.set-once-format-painter`
- `sheet.command.set-overline`
- `sheet.command.set-protection`
- `sheet.command.set-range-bold`
- `sheet.command.set-range-custom-metadata`
- `sheet.command.set-range-font-decrease`
- `sheet.command.set-range-font-family`
- `sheet.command.set-range-font-increase`
- `sheet.command.set-range-fontsize`
- `sheet.command.set-range-italic`
- `sheet.command.set-range-protection-from-context-menu`
- `sheet.command.set-range-stroke`
- `sheet.command.set-range-subscript`
- `sheet.command.set-range-superscript`
- `sheet.command.set-range-text-color`
- `sheet.command.set-range-underline`
- `sheet.command.set-range-values`
- `sheet.command.set-row-data`
- `sheet.command.set-row-frozen`
- `sheet.command.set-row-header-width`
- `sheet.command.set-row-height`
- `sheet.command.set-row-is-auto-height`
- `sheet.command.set-rows-hidden`
- `sheet.command.set-scroll-relative`
- `sheet.command.set-selected-cols-visible`
- `sheet.command.set-selected-rows-visible`
- `sheet.command.set-selection-frozen`
- `sheet.command.set-sheet-image`
- `sheet.command.set-shrink-to-fit`
- `sheet.command.set-specific-rows-visible`
- `sheet.command.set-stroke`
- `sheet.command.set-style`
- `sheet.command.set-tab-color`
- `sheet.command.set-table-config`
- `sheet.command.set-table-filter`
- `sheet.command.set-table-sort-state`
- `sheet.command.set-text-color`
- `sheet.command.set-text-rotation`
- `sheet.command.set-text-wrap`
- `sheet.command.set-underline`
- `sheet.command.set-vertical-text-align`
- `sheet.command.set-workbook-name`
- `sheet.command.set-worksheet-activate`
- `sheet.command.set-worksheet-background-image`
- `sheet.command.set-worksheet-col-width`
- `sheet.command.set-worksheet-column-count`
- `sheet.command.set-worksheet-default-style`
- `sheet.command.set-worksheet-hidden`
- `sheet.command.set-worksheet-name`
- `sheet.command.set-worksheet-order`
- `sheet.command.set-worksheet-permission-points`
- `sheet.command.set-worksheet-protection`
- `sheet.command.set-worksheet-range-theme-style`
- `sheet.command.set-worksheet-right-to-left`
- `sheet.command.set-worksheet-row-count`
- `sheet.command.set-worksheet-show`
- `sheet.command.set-zoom-ratio`
- `sheet.command.set-zoom-ratio-from-toolbar`
- `sheet.command.smart-toggle-filter`
- `sheet.command.sort-range`
- `sheet.command.sort-range-asc`
- `sheet.command.sort-range-asc-ctx`
- `sheet.command.sort-range-asc-ext`
- `sheet.command.sort-range-asc-ext-ctx`
- `sheet.command.sort-range-custom`
- `sheet.command.sort-range-custom-ctx`
- `sheet.command.sort-range-desc`
- `sheet.command.sort-range-desc-ctx`
- `sheet.command.sort-range-desc-ext`
- `sheet.command.sort-range-desc-ext-ctx`
- `sheet.command.split-text-to-columns`
- `sheet.command.table-insert-col`
- `sheet.command.table-insert-column-at`
- `sheet.command.table-insert-row`
- `sheet.command.table-insert-row-at`
- `sheet.command.table-remove-col`
- `sheet.command.table-remove-column-at`
- `sheet.command.table-remove-row`
- `sheet.command.text-to-number`
- `sheet.command.toggle-cell-checkbox`
- `sheet.command.toggle-flip-drawings`
- `sheet.command.toggle-gridlines`
- `sheet.command.toggle-note-popup`
- `sheet.command.ungroup-sheet-image`
- `sheet.command.unregister-worksheet-range-theme-style`
- `sheet.command.update-note`
- `sheet.command.updateDataValidationRuleRange`
- `sheet.command.view-sheet-permission-from-context-menu`
- `sheet.command.view-sheet-permission-from-sheet-bar`

### `sheet.mutation` (71)

- `sheet.mutation.add-conditional-rule`
- `sheet.mutation.add-range-protection`
- `sheet.mutation.add-range-theme`
- `sheet.mutation.add-table`
- `sheet.mutation.add-worksheet-merge`
- `sheet.mutation.add-worksheet-protection`
- `sheet.mutation.conditional-formatting-formula-mark-dirty`
- `sheet.mutation.copy-worksheet-end`
- `sheet.mutation.data-validation-formula-mark-dirty`
- `sheet.mutation.delete-conditional-rule`
- `sheet.mutation.delete-range-protection`
- `sheet.mutation.delete-table`
- `sheet.mutation.delete-worksheet-protection`
- `sheet.mutation.empty`
- `sheet.mutation.insert-col`
- `sheet.mutation.insert-range`
- `sheet.mutation.insert-row`
- `sheet.mutation.insert-sheet`
- `sheet.mutation.mark-dirty-filter-change`
- `sheet.mutation.move-columns`
- `sheet.mutation.move-conditional-rule`
- `sheet.mutation.move-range`
- `sheet.mutation.move-rows`
- `sheet.mutation.register-worksheet-range-theme-style`
- `sheet.mutation.remove-col`
- `sheet.mutation.remove-note`
- `sheet.mutation.remove-range-theme`
- `sheet.mutation.remove-rows`
- `sheet.mutation.remove-sheet`
- `sheet.mutation.remove-worksheet-merge`
- `sheet.mutation.remove-worksheet-range-theme-style`
- `sheet.mutation.remove.numfmt`
- `sheet.mutation.reorder-range`
- `sheet.mutation.set-col-data`
- `sheet.mutation.set-col-hidden`
- `sheet.mutation.set-col-visible`
- `sheet.mutation.set-conditional-rule`
- `sheet.mutation.set-drawing-apply`
- `sheet.mutation.set-frozen`
- `sheet.mutation.set-gridlines-color`
- `sheet.mutation.set-range-protection`
- `sheet.mutation.set-range-theme`
- `sheet.mutation.set-range-values`
- `sheet.mutation.set-row-data`
- `sheet.mutation.set-row-hidden`
- `sheet.mutation.set-row-visible`
- `sheet.mutation.set-sheet-table`
- `sheet.mutation.set-tab-color`
- `sheet.mutation.set-table-filter`
- `sheet.mutation.set-workbook-name`
- `sheet.mutation.set-worksheet-background-image`
- `sheet.mutation.set-worksheet-col-width`
- `sheet.mutation.set-worksheet-column-count`
- `sheet.mutation.set-worksheet-default-style`
- `sheet.mutation.set-worksheet-hidden`
- `sheet.mutation.set-worksheet-name`
- `sheet.mutation.set-worksheet-order`
- `sheet.mutation.set-worksheet-permission-points`
- `sheet.mutation.set-worksheet-protection`
- `sheet.mutation.set-worksheet-range-theme-style`
- `sheet.mutation.set-worksheet-right-to-left`
- `sheet.mutation.set-worksheet-row-auto-height`
- `sheet.mutation.set-worksheet-row-count`
- `sheet.mutation.set-worksheet-row-height`
- `sheet.mutation.set-worksheet-row-is-auto-height`
- `sheet.mutation.set.numfmt`
- `sheet.mutation.toggle-gridlines`
- `sheet.mutation.toggle-note-popup`
- `sheet.mutation.unregister-worksheet-range-theme-style`
- `sheet.mutation.update-note`
- `sheet.mutation.update-note-position`

### `sheet.operation` (52)

- `sheet.operation.Auto-image-crop`
- `sheet.operation.add-drawing-comment`
- `sheet.operation.add-note-popup`
- `sheet.operation.apply-filter`
- `sheet.operation.cancel-mark-dirty-row-auto-height`
- `sheet.operation.clear-drawing-transformer`
- `sheet.operation.close-filter-panel`
- `sheet.operation.close-hyper-link-popup`
- `sheet.operation.close-image-crop`
- `sheet.operation.close.numfmt.panel`
- `sheet.operation.disable-crosshair-highlight`
- `sheet.operation.edit-sheet-image`
- `sheet.operation.enable-crosshair-highlight`
- `sheet.operation.hide-data-validation-dropdown`
- `sheet.operation.image-reset-size`
- `sheet.operation.insert-hyper-link`
- `sheet.operation.insert-hyper-link-toolbar`
- `sheet.operation.mark-dirty-row-auto-height`
- `sheet.operation.open-comment-panel`
- `sheet.operation.open-filter-panel`
- `sheet.operation.open-hyper-link-edit-panel`
- `sheet.operation.open-image-crop`
- `sheet.operation.open-table-filter-panel`
- `sheet.operation.open-table-selector`
- `sheet.operation.open.conditional.formatting.panel`
- `sheet.operation.open.numfmt.panel`
- `sheet.operation.rename-sheet`
- `sheet.operation.scroll-to-cell`
- `sheet.operation.scroll-to-range`
- `sheet.operation.set-activate-cell-edit`
- `sheet.operation.set-cell-edit-visible`
- `sheet.operation.set-cell-edit-visible-arrow`
- `sheet.operation.set-cell-edit-visible-f2`
- `sheet.operation.set-crosshair-highlight-color`
- `sheet.operation.set-drawing-align-bottom`
- `sheet.operation.set-drawing-align-center`
- `sheet.operation.set-drawing-align-horizon`
- `sheet.operation.set-drawing-align-left`
- `sheet.operation.set-drawing-align-middle`
- `sheet.operation.set-drawing-align-right`
- `sheet.operation.set-drawing-align-top`
- `sheet.operation.set-drawing-align-vertical`
- `sheet.operation.set-format-painter`
- `sheet.operation.set-image-align`
- `sheet.operation.set-scroll`
- `sheet.operation.set-selections`
- `sheet.operation.set-worksheet-active`
- `sheet.operation.set-zoom-ratio`
- `sheet.operation.show-comment-modal`
- `sheet.operation.show-data-validation-dropdown`
- `sheet.operation.toggle-comment-panel`
- `sheet.operation.toggle-crosshair-highlight`

### `sheets.command` (9)

- `sheets.command.add-hyper-link`
- `sheets.command.add-rich-hyper-link`
- `sheets.command.cancel-hyper-link`
- `sheets.command.cancel-rich-hyper-link`
- `sheets.command.clear-range-data-validation`
- `sheets.command.update-data-validation-options`
- `sheets.command.update-data-validation-setting`
- `sheets.command.update-hyper-link`
- `sheets.command.update-rich-hyper-link`

### `sheets.mutation` (5)

- `sheets.mutation.add-hyper-link`
- `sheets.mutation.remove-hyper-link`
- `sheets.mutation.update-hyper-link`
- `sheets.mutation.update-hyper-link-ref`
- `sheets.mutation.update-rich-hyper-link`

### `sidebar.operation` (7)

- `sidebar.operation.defined-name`
- `sidebar.operation.doc-header-footer-panel`
- `sidebar.operation.doc-image`
- `sidebar.operation.doc-paragraph-setting-panel`
- `sidebar.operation.doc-section-setting-panel`
- `sidebar.operation.sheet-image`
- `sidebar.operation.slide-shape`

### `slide.command` (4)

- `slide.command.add-text`
- `slide.command.insert-float-image`
- `slide.command.insert-float-shape.ellipse`
- `slide.command.insert-float-shape.rectangle`

### `slide.operation` (9)

- `slide.operation.activate-slide`
- `slide.operation.add-text`
- `slide.operation.append-slide`
- `slide.operation.delete-element`
- `slide.operation.edit-arrow`
- `slide.operation.insert-float-shape.ellipse`
- `slide.operation.insert-float-shape.rectangle`
- `slide.operation.set-slide-page-thumb`
- `slide.operation.update-element`

### `thread-comment-ui.operation` (1)

- `thread-comment-ui.operation.set-active-comment`

### `thread-comment.command` (5)

- `thread-comment.command.add-comment`
- `thread-comment.command.delete-comment`
- `thread-comment.command.delete-comment-tree`
- `thread-comment.command.resolve-comment`
- `thread-comment.command.update-comment`

### `thread-comment.mutation` (5)

- `thread-comment.mutation.add-comment`
- `thread-comment.mutation.delete-comment`
- `thread-comment.mutation.resolve-comment`
- `thread-comment.mutation.update-comment`
- `thread-comment.mutation.update-comment-ref`

### `ui-sheet.command` (1)

- `ui-sheet.command.show-menu-list`

### `ui.command` (3)

- `ui.command.clear-formatting`
- `ui.command.replace-all-matches`
- `ui.command.replace-current-match`

### `ui.operation` (10)

- `ui.operation.activate-format-painter`
- `ui.operation.cancel-format-painter`
- `ui.operation.close-find-dialog`
- `ui.operation.continuous-format-painter`
- `ui.operation.focus-selection`
- `ui.operation.go-to-next-match`
- `ui.operation.go-to-previous-match`
- `ui.operation.open-feature-search`
- `ui.operation.open-find-dialog`
- `ui.operation.open-replace-dialog`
