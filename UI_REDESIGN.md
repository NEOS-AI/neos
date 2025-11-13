# NEOS UI Redesign - Claude Style

## Overview

NEOS UI has been redesigned to follow Claude's minimalist, typography-focused dark theme design language. The redesign maintains all existing functionality while significantly improving visual aesthetics, user experience, and accessibility.

## Design Principles

### 1. **Minimalist & Clean**
- Reduced visual clutter
- Focus on content and typography
- Subtle shadows and borders
- Generous whitespace

### 2. **Dark Theme First**
- Deep, rich background colors
- High contrast text for readability
- Subtle color accents
- Comfortable for extended use

### 3. **Typography-Centric**
- Inter font family
- Clear hierarchy with font sizes
- Optimal line heights for readability
- Careful letter spacing

### 4. **Micro-interactions**
- Smooth transitions (200ms)
- Subtle hover effects
- Clear focus states
- Responsive feedback

## Design System

### Color Tokens

All colors are defined as CSS variables and Tailwind tokens:

```css
/* Background */
--color-bg-canvas: #0B0D0F       /* Main background */
--color-bg-surface: #111317      /* Cards, panels */

/* Text */
--color-text-primary: #E6E7E9    /* Main text */
--color-text-secondary: #A4A8AE  /* Secondary text */
--color-text-muted: #7A7F87      /* Hints, labels */

/* Lines & Borders */
--color-line-soft: #1A1D23       /* Subtle borders */

/* Brand */
--color-brand-accent: #FF7A45    /* Primary actions, highlights */

/* Interactive */
--action-hover: rgba(255,255,255,0.04)  /* Hover state */

/* Chips */
--color-chip-bg: #0F1217         /* Chip background */
--color-chip-line: #1D2128       /* Chip border */
```

### Typography Scale

```typescript
"display-1": 40px / 1.2 / 600    // Hero headings
"body-m": 15px / 1.6             // Body text
"label-s": 12px / 1.4 / 0.02em   // Small labels, uppercase
```

### Spacing & Layout

- **Sidebar width**: 280px
- **Main content max-width**: 860px (Chat Composer), 1024px (Home)
- **Border radius**: 16px (2xl), 24px (3xl)
- **Box shadows**:
  - `soft`: 0 4px 16px rgba(0, 0, 0, 0.12)
  - `soft-lg`: 0 8px 24px rgba(0, 0, 0, 0.15)
  - `glow`: 0 0 20px rgba(255, 122, 69, 0.2)

## New Components

### 1. GreetingHero (`components/home/GreetingHero.tsx`)

Large, welcoming greeting section with icon and text.

**Props:**
- `greeting?: string` - Main greeting text
- `subtext?: string` - Optional subtext

**Features:**
- Time-based greeting (Good morning/afternoon/evening)
- Icon with accent color background
- Responsive text sizing

### 2. ChatComposer (`components/home/ChatComposer.tsx`)

Central input component with auto-resize textarea.

**Props:**
- `onSend: (message: string) => void` - Message send handler
- `placeholder?: string` - Input placeholder
- `disabled?: boolean` - Disable state

**Features:**
- Auto-resize textarea (1-4 lines)
- Keyboard shortcuts (Cmd+Enter to send)
- Attachment button (UI only)
- Clear focus ring for accessibility
- Pill-shaped design

### 3. QuickActions (`components/home/QuickActions.tsx`)

Chip-style quick action buttons.

**Props:**
- `actions?: QuickAction[]` - Array of action configurations

**Features:**
- Icon + Label chips
- Hover animations (raise + ring)
- Flexible grid layout
- Keyboard accessible

### 4. ExampleCards (`components/home/ExampleCards.tsx`)

Grid of example/feature cards.

**Props:**
- `cards: ExampleCard[]` - Card data
- `columns?: 1 | 2 | 3` - Grid columns

**Features:**
- Icon + Title + Description
- Arrow indicator on hover
- Responsive grid (1/2/3 columns)
- Scale animation on hover
- Focus ring for accessibility

### 5. ModeSelector (`components/home/ModeSelector.tsx`)

Dropdown selector for chat modes.

**Props:**
- `modes: Mode[]` - Available modes
- `selectedMode: string` - Currently selected mode
- `onModeChange: (id: string) => void` - Selection handler
- `label?: string` - Selector label

**Features:**
- Dropdown with checkmark indicator
- Mode descriptions
- Click-outside to close
- Keyboard navigation support
- Smooth open/close animation

### 6. TopBar (`components/home/TopBar.tsx`)

Sticky top bar with scroll behavior.

**Props:**
- `showModeSelector?: boolean`
- `modes?: Mode[]`
- `selectedMode?: string`
- `onModeChange?: (id: string) => void`
- `showSettings?: boolean`
- `onSettingsClick?: () => void`

**Features:**
- Transparent by default
- Background + border on scroll
- Right-aligned actions
- Sticky positioning

### 7. Updated Sidebar (`components/chat/Sidebar.tsx`)

Redesigned navigation sidebar.

**Features:**
- 280px fixed width
- Search functionality
- Active conversation highlighting with left border
- Hover actions (delete)
- Search filtering
- Section headers with typography
- NEOS logo with brand accent

## Updated Pages

### Home Page (`app/page.tsx`)

Complete redesign following Claude's home screen pattern:

**Layout Structure:**
1. **TopBar** - Mode selector and settings
2. **Main Stage** (max-w-4xl, centered)
   - Greeting Hero
   - Chat Composer
   - Quick Actions
   - Example Cards
   - Recent Conversations (if any)
3. **Footer** - Simple text hint

**Responsive:**
- Full width on mobile
- Centered content with padding on tablet+
- Grid adjusts from 1 to 2 columns

### Chat Page (`app/chat/[id]/page.tsx`)

Updated to use new design tokens:

**Layout:**
- Sidebar (280px)
- Main chat area
  - Header with mode selector
  - Message list
  - Input box

**Color Updates:**
- Background: `bg-bg-canvas`
- Header: `bg-bg-surface` with `border-line-soft`
- Uses new design tokens throughout

## Accessibility Features

### Color Contrast
All text meets **WCAG AA** standards:
- Primary text: #E6E7E9 on #0B0D0F (ratio > 12:1)
- Secondary text: #A4A8AE on #0B0D0F (ratio > 7:1)
- Muted text: #7A7F87 on #0B0D0F (ratio > 4.5:1)

### Keyboard Navigation
- All interactive elements are keyboard accessible
- Clear focus rings (`ring-brand-accent/50`)
- Tab order follows visual hierarchy
- Keyboard shortcuts documented visually

### ARIA Labels
- Semantic HTML5 elements (`nav`, `main`, `header`)
- `aria-label` on icon-only buttons
- `aria-expanded` on dropdowns
- `aria-selected` on mode options
- `role="listbox"` on dropdown menus

### Screen Reader Support
- Descriptive button labels
- Proper heading hierarchy
- Skip to content patterns
- Status announcements

## Responsive Breakpoints

Using Tailwind's default breakpoints:

```
sm:  640px
md:  768px
lg:  1024px
xl:  1280px
```

**Mobile-first approach:**
- Base styles for mobile
- `md:` prefix for tablet
- `lg:` prefix for desktop

**Key responsive features:**
- Sidebar: Hidden on mobile (could add hamburger menu)
- Grids: 1 column → 2 columns → 3 columns
- Padding: Reduced on mobile
- Font sizes: Slightly smaller on mobile

## Browser Support

Tested and working on:
- ✅ Chrome/Edge (latest)
- ✅ Firefox (latest)
- ✅ Safari (latest)

**CSS Features Used:**
- CSS Grid
- Flexbox
- CSS Variables
- Backdrop filter (with fallback)
- CSS Transitions

## Performance Considerations

### Build Size
```
Route (app)                Size     First Load JS
┌ ○ /                      4.16 kB   101 kB
└ ƒ /chat/[id]            51.4 kB   148 kB
```

### Optimizations
- No heavy animations (only transforms and opacity)
- Efficient CSS with Tailwind's purge
- Minimal JavaScript in components
- Lazy loading for heavy components
- Debounced search in Sidebar

## Migration Guide

### For Developers

**Old colors → New colors:**
```tsx
// Before
className="bg-claude-darker text-claude-text"

// After
className="bg-bg-canvas text-text-primary"
```

**Using new components:**
```tsx
import GreetingHero from "@/components/home/GreetingHero";
import ChatComposer from "@/components/home/ChatComposer";
import QuickActions from "@/components/home/QuickActions";

// In your component
<GreetingHero greeting="Welcome back" />
<ChatComposer onSend={handleSend} />
<QuickActions actions={myActions} />
```

### Component API

All components accept standard React props:
- `className` - Additional Tailwind classes
- `style` - Inline styles (avoid if possible)
- `aria-*` - Accessibility attributes
- `data-*` - Custom data attributes

### Customization

To customize colors:
1. Edit `app/globals.css` CSS variables
2. Update `tailwind.config.ts` color tokens
3. Rebuild: `npm run build`

Example:
```css
:root {
  --color-brand-accent: 255 100 50; /* Change accent color */
}
```

## Testing Checklist

### Visual Testing
- ✅ Light/Dark mode (dark only currently)
- ✅ All breakpoints (mobile, tablet, desktop)
- ✅ All interactive states (hover, focus, active, disabled)
- ✅ Text overflow and truncation
- ✅ Empty states

### Functional Testing
- ✅ Navigation works
- ✅ Forms submit correctly
- ✅ Dropdowns open/close
- ✅ Search filters conversations
- ✅ Keyboard shortcuts work
- ✅ Messages send successfully

### Accessibility Testing
- ✅ Keyboard navigation
- ✅ Screen reader support
- ✅ Color contrast
- ✅ Focus indicators
- ✅ ARIA labels

### Performance Testing
- ✅ Build succeeds
- ✅ No console errors
- ✅ Fast page loads
- ✅ Smooth animations
- ✅ No layout shifts

## Known Limitations

1. **No Light Mode**: Currently only dark theme is implemented
2. **Mobile Sidebar**: Sidebar is hidden on mobile; hamburger menu could be added
3. **Image Upload**: Attachment button is UI-only, not functional
4. **Mode Persistence**: Selected mode doesn't persist across sessions
5. **Search**: Only filters by title, not by message content

## Future Enhancements

### Short-term
- [ ] Light mode variant
- [ ] Mobile sidebar with hamburger menu
- [ ] Conversation search by content
- [ ] Keyboard shortcuts panel (Cmd+K)
- [ ] Settings modal redesign

### Long-term
- [ ] Customizable themes
- [ ] Color scheme editor
- [ ] Animation preferences
- [ ] Compact/comfortable density options
- [ ] Custom fonts

## Credits

Design inspired by:
- Claude.ai interface
- Vercel's design system
- Linear's UI patterns
- Tailwind UI components

Built with:
- Next.js 14
- React 18
- Tailwind CSS 3
- lucide-react icons
- TypeScript 5

---

**Documentation Version**: 1.0
**Last Updated**: 2025-11-13
**Author**: Claude (Anthropic)
