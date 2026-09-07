---
name: reference-matched-presentations
description: Refine or rebuild editable PowerPoint presentations to match supplied visual references, including image references, while preserving approved content and layout. Use for reference-led visual polish, matching earlier meeting slides, or making native slides as polished as generated images; includes the EAGLE Meeting 0830 profile.
---

# Reference-matched presentations

Use the available Presentations skill for authoring, rendering, and package validation. This skill adds reference fidelity and scope decisions; it does not replace that workflow.

## Establish the visual authority

1. Inspect the actual reference images or rendered reference slides before selecting icons, generating assets, or styling the deck. Read all pages of a small reference batch together, then inspect representative pages at readable size. Text extraction alone cannot establish the visual style.
2. Distinguish the visual reference, the content sources, and the latest factual specification. An older reference controls appearance, not current architecture or experiment results.
3. Record the observed typography, palette, line weight, icon construction, fills, corner decorations, emphasis treatment, and spacing. Use concrete observations instead of labels such as elegant or premium.
4. When the user approves content and layout, preserve the wording, data, reading order, and major geometry. Allow local spacing adjustments to fit icons, but do not redesign the structure or rewrite the argument without a content request.
5. For EAGLE Meeting 0830, read [the local visual profile](references/meeting-0830.md). Do not apply its floral palette to unrelated references.

## Match the graphics, not just the colors

- Choose one coherent icon family with consistent line thickness, corner treatment, detail level, and optical scale. Match the reference's actual construction: a flat outline reference calls for flat outline icons.
- Flaticon, including its official Uicons distribution, is a useful source when suitable. Prefer a single outline family; recolor it to the reference palette. Inspect the selected icons at their intended slide size.
- Preserve source and license information and include required attribution in the deck. Use authorized public downloads or official packages; do not bypass login, payment, or access controls. If the chosen source cannot supply suitable assets, use another appropriate library or native shapes and state the substitution.
- Generated standalone icons are optional when they materially help and fit the reference. Provide the actual reference to the generation tool when possible. Reject mismatched results before inserting them across the deck.
- A matching palette does not make engraving, metallic shading, wreaths, ornate emblems, or pictorial illustrations compatible with simple line icons. Do not add such effects merely to make a deck look more polished.
- Use icons to represent the content accurately. Preserve distinctions between historical and current operators; do not give a historical operator a new operator's identity.

## Keep PowerPoint editable

- Build text, cards, separators, connectors, tables, charts, and diagrams as native PowerPoint elements. Prefer editable vector paths for simple icons; suitable small SVG or PNG icons are acceptable when native paths are impractical.
- Do not generate or flatten whole slides into images. A full-slide reference image is a visual reference, not the finished slide background containing text and diagrams.
- Reuse the existing template, theme, and layouts. Refine hierarchy and alignment before adding decoration. Do not introduce gradients, shadows, double borders, or extra ornaments unless the reference supports them.
- If a reusable template is requested, use a real `.potx` with theme fonts, theme colors, masters, layouts, and usable placeholders. When the user requests one template, deliver one canonical template file. A populated report is a separate `.pptx`.
- For a progress report assembled from dated sources, when requested, lead with a concise change chronology and what each revision did, then explain each experiment. Update historical diagrams to the latest supported design while keeping historical measurements labeled and unchanged.

## Verify before replacing the deliverable

1. Render representative pages with different structures early, especially diagrams and dense cards. Compare them with the original references, not only with the previous draft. Check badge/icon separation, heading clearance, optical scale, and consistent strokes.
2. Render and inspect all final slides. Recheck locally changed pages after a spacing fix. Do not claim native PowerPoint execution when only a library renderer was used.
3. Compare slide text, speaker notes, tables, chart categories, series, and values against the approved deck or source data. Allow only intentional additions such as icon credits. Resolve chart parts through package relationships; do not assume a single chart directory or accept a zero-chart comparison as success.
4. Validate package integrity, slide count, text bounds, theme fonts, native table/chart ownership, and image usage. Confirm no rejected generated graphics or full-slide raster substitutions remain.
5. Replace the requested output only after these checks. Preserve unrelated files and follow the workspace's commit policy. Keep scratch builds and rejected candidates out of the delivery folder.

For OpenXML cloning, preserve unique creation identifiers, explicit no-bullet paragraph formatting where needed, valid package namespaces, and an `utf-8` XML declaration. These details can affect import and rendering even when the ZIP opens successfully.
