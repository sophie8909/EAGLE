# EAGLE Meeting 0830 visual profile

Use only when the user selects the 0830 EAGLE batch or explicitly requests this visual system. These observations do not supersede new user direction.

## Sources to inspect

Resolve these paths from the EAGLE repository root; the recorded workspace is `D:/Project/EAGLE`:

- `Meeting/20260830_eagle_current_workflow.png`
- `Meeting/20260830_eagle_genotype_phenotype.png`
- `Meeting/20260830_eagle_initial_policy_experiments.png`
- `Meeting/20260830_eagle_operator_modes.png`
- `Meeting/20260830_eagle_reflection_operators.png`
- Reusable native template: `Meeting/template/EAGLE.potx`
- Editable implementation example: `Meeting/20260910_eagle_progress.pptx`

Inspect the five PNGs as the primary visual authority. The editable implementation is a construction example; it must not replace direct comparison with the originals. Locate moved sources before relying on stale paths.

## Standard reusable layouts

The reusable native template is named `EAGLE` and uses the `EAGLE` master and theme. Keep the PowerPoint gallery generic with these 12 standard layouts:

`封面`、`章節標題`、`標題及內容`、`兩項內容`、`比較`、`三欄內容`、`圖片及標題`、`內容與圖片`、`標題及表格`、`標題及圖表`、`僅標題`、`空白`

Never create one layout per report slide. Migrate report-specific artwork and decorative objects into native slide objects while preserving their appearance, so the gallery remains reusable.

## Observed design

- Warm ivory background, burgundy serif headings, restrained rose floral corner linework, fine rose rounded card borders, and ample separation between title, subtitle, and content.
- Simple rose outline symbols: seedling, people, DNA, document/code, gear, gamepad, chart, trophy, compass, target, ranking, and discussion. These are small explanatory symbols, not illustrated crests.
- Gold marks emphasis or a selected item. Do not cover every icon in gold. Keep ordinary cards mostly flat and the linework delicate.
- Circular numbered badges sit on the top card border. Put icons below the badges with a visible gap, followed by heading, small gold emphasis pill when appropriate, divider, and readable body.
- Native template theme: `EAGLE`, with Source Han Serif TW as the default font. Preserve explicit serif heading emphasis; do not silently swap fonts. The originals have strong heading weight, so inspect the actual rendered font appearance.
- Template palette: background `#FCF8F5`, heading `#47171C`, rose `#CF8792`, border `#DEB4BA`, gold `#C69B45`, pale emphasis `#F4DEA0`, body `#423C3B`. The corrected line-icon version uses `#C77E8C` for clearer rose strokes and `#C19B4A` for selected gold icons.
- Existing canvas: 1672 × 941 CSS pixels, corresponding to 15925800 × 8963025 EMU. Reuse the source deck's actual dimensions.
- Keep the original 0830 visual-reference profile and historic colors. The current soft eagle background is approved for the EAGLE template.

## Icon sourcing used in the corrected workflow

Official Flaticon Uicons, regular rounded outline family:

- https://www.flaticon.com/uicons
- https://www.flaticon.com/uicons/get-started
- Official package: `@flaticon/flaticon-uicons`

Check current package contents and terms before use. In the observed package, the regular-rounded icons were supplied as a font plus CSS mappings. Glyph outlines were converted to native PowerPoint paths, keeping them editable and independent of an installed icon font. SVG sources may be simpler when provided. Include the required credit, for example `Uicons by Flaticon · flaticon.com/uicons`, visibly without colliding with the footer or floral corners.

The rejected direction was rose-and-gold engraved compass, parchment/quill, and heraldic shield illustrations with wreaths. Their color palette matched, but their texture, detail, and form did not. Do not reuse them as the reference style.
