# neos-web Blue-Black Dark UI Design

Date: 2026-05-20
Status: Approved for implementation planning

## Goal

Update `neos-web` from its current dark gray interface to a cohesive black and deep-blue visual system inspired by the provided reference image. The result should feel like one continuous AI work surface, not only a decorated empty state.

The selected direction is **B. 전체 작업공간 블루블랙**:

- Use near-black page foundations.
- Add subtle deep-blue depth across the workspace.
- Keep the reference image's blue central bloom most visible on the empty chat screen.
- Keep active chat views calmer so long conversations remain readable.

## Scope

The redesign applies to the main chat experience:

- Global dark theme tokens in `web/app/globals.css`.
- Browser theme color in `web/app/layout.tsx`.
- Chat shell and bottom composer area in `web/components/chat.tsx`.
- Empty and populated message area in `web/components/messages.tsx`.
- Empty-state greeting in `web/components/greeting.tsx`.
- Prompt composer, attachment button, send/stop buttons, and compact model selector in `web/components/multimodal-input.tsx`.
- Header controls in `web/components/chat-header.tsx`.
- Sidebar brand/header and history surface in `web/components/app-sidebar.tsx`.
- Shared sidebar color behavior through the existing sidebar tokens.

Out of scope for this pass:

- New product navigation or information architecture.
- Functional changes to chat, uploads, model selection, auth, or history.
- A separate light-theme redesign.
- Full replacement of every UI primitive. Shared tokens should carry most of the update.

## Visual System

### Palette

Use a restrained blue-black palette:

- `background`: near black, around `#030407` to `#06070b`.
- `card` / `popover`: dark blue-black surfaces, around `#090d16` to `#0d1220`.
- `sidebar`: slightly separated black-blue surface.
- `border` / `input`: low-contrast blue-gray lines.
- `primary` / `ring`: clear electric blue for focus and active affordances.
- `foreground`: cool white, with muted text in blue-gray.

The palette should avoid a flat gray wash. Surfaces need enough blue undertone to match the reference, but text and reading areas should stay quiet.

### Background Treatment

The page background should use layered CSS backgrounds rather than image assets:

- A near-black base.
- A large radial blue glow in the central working area.
- Optional subtle edge darkening through gradients.

The glow should be strongest when the chat has no messages, because that is where the visual reference is most relevant. Once messages exist, the same system can remain present but should not compete with message content.

### Components

The composer should read as a refined, dark pill/panel:

- Deep blue-black fill.
- Soft blue border.
- Focus state using the primary blue ring.
- Subtle shadow that blends into the background.

The sidebar should be integrated into the same color system:

- No bright gray panels.
- Hover and active states should use low-opacity blue surfaces.
- The app label should become `NEOS` rather than generic `Chatbot`.

The chat header should stay functional and restrained:

- Transparent or translucent over the same background system.
- Controls should use token-driven dark surfaces and blue focus states.

Message areas should prioritize legibility:

- User and assistant messages should keep sufficient text contrast.
- Bubble or block backgrounds should remain subtle.
- Code, artifacts, and popovers should inherit the refreshed token colors.

## Accessibility And Responsiveness

- Maintain WCAG AA contrast for primary and secondary text against the new surfaces.
- Preserve keyboard focus visibility with the refreshed blue ring token.
- Check mobile widths so header controls and the composer do not overlap.
- Avoid viewport-scaled font sizes. Keep typography stable and predictable.
- Keep scrollbars visible enough to discover, but visually quiet.

## Implementation Strategy

1. Update global dark CSS variables first, including sidebar and chart tokens.
2. Add reusable background utility classes for the blue-black workspace and empty-state bloom.
3. Apply those utilities to the chat shell and message area.
4. Refresh component-level classes where hard-coded gray/zinc styling prevents the tokens from showing through.
5. Update the browser dark theme color to match the new background.
6. Run build/type checks and visually inspect empty chat, populated chat, sidebar, model selector, and mobile layout.

## Verification

Run:

- `pnpm --dir web build`

Then inspect in a browser:

- Empty chat screen at desktop width.
- Empty chat screen at mobile width.
- Populated chat screen if seeded or reachable.
- Sidebar expanded/collapsed and mobile sheet.
- Model selector dialog.
- Composer focus, disabled send, active send, stop state, attachment button.

Success criteria:

- The UI visibly matches the reference's black and deep-blue mood.
- The entire chat workspace feels visually cohesive.
- No major text contrast regression.
- No header/composer overlap on mobile.
- Existing chat functionality remains unchanged.
