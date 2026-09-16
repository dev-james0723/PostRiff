# Calendar

Month, week and day calendar laid out after the [Untitled UI calendar](https://www.untitledui.com/components/calendars) anatomy. Untitled UI's own React calendar is a PRO component (`npx untitledui@latest add calendar` answers "requires PRO access"), so this one is written here on the same libraries its docs list: `@internationalized/date` for dates and `@react-aria/i18n` for locale-aware wording. The day panel's month picker uses `react-aria-components`.

The folder mirrors Untitled UI's `components/application/calendar/` path. With a PRO licence, `npx untitledui login` and then `add calendar` would land next to these files; compare the two before replacing anything.

- `calendar.tsx`: `Calendar` (header, the three views, day panel), `useCurrentTime`, `useLocalTimeZone`
- `config.ts`: `CalendarEvent`, the nine event colours, views, layout constants (96px per hour, 30 minute minimum block, 3 chips per month cell)
- `month-view.tsx`, `time-grid.tsx` (week and day), `event-button.tsx` (chip or block, with an optional details popover), `mini-calendar.tsx`
- `utils.ts`: grid days, visible range, period paging, ISO week, events by day, overlap layout

## Using it

```tsx
const timeZone = useLocalTimeZone(); // null on the server; render a skeleton until it is set
const [view, setView] = useState<CalendarView>('month');
const [date, setDate] = useState(() => today(timeZone!));

const events: CalendarEvent<Post>[] = posts.map((post) => ({
  id: post.id,
  title: post.title,
  start: fromDate(new Date(post.utc), timeZone!), // an exact moment, in the zone the grid is drawn in
  color: 'blue',
  status: 'Scheduled', // read with the title: colour never carries meaning alone
  icon: <ChannelIcon platform={post.platform} size='xs' />,
  data: post
}));

<Calendar
  events={events}
  view={view}
  onViewChange={setView}
  focusedDate={date}
  onFocusedDateChange={setDate}
  timeZone={timeZone!}
  noun={{ one: 'post', other: 'posts' }}
  renderEventDetails={(event, context) => <PostDetails post={event.data} compact={context === 'list'} />}
/>;
```

`features/calendar/calendar-view.tsx` is the real use: reviews and publishing jobs from the workspace snapshot, with view and date kept in the address (`?view=week&date=2026-09-17`) through nuqs.

## Concepts

- **`CalendarDate` vs `ZonedDateTime`.** A `CalendarDate` is a day with no time or zone (`2026-09-16`); the views page by it. A `ZonedDateTime` is a moment in a named zone; events use it, so "which day does 23:30 UTC fall on" is answered in the viewer's zone, not the server's.
- **Time zone.** `getLocalTimeZone()` only means something in the browser. `useLocalTimeZone()` returns `null` on the server and during hydration so no zone-dependent text is rendered twice with different values.
- **Locale.** `Calendar` wraps its content in `I18nProvider` (`locale`, default `en`, matching `lib/time.ts`). Weekday names, month titles, hour labels and ranges all come from `useDateFormatter`. `firstDayOfWeek` (default `mon`) overrides the locale's week start; the "Week N" badge is ISO and only shows when weeks start on Monday.
- **Moments on a ruler.** Week and day views place an event at its exact minute. Without `end`, a block is 30 minutes tall so the title and time stay legible; the time label, not the height, is the truth. Overlapping blocks split the column into lanes.
- **Month density.** Up to three chips per cell; a busier day shows two plus "+N more", which opens that day. Below `md` chips become dots and the whole cell opens the day.

## Keyboard and screen readers

- Month grid: `role="grid"`, one tab stop on the focused date. Arrow keys move by day and week, Home/End to the week's ends, PageUp/PageDown by month (with Shift, by year); focus follows into the next month. Enter opens the day. Chips are skipped by Tab; the day view lists every event.
- Each date's name says its event count; each chip and block is named "title, status, time".
- The month picker is React Aria's calendar grid, with the same keys.
- Motion: periods slide in the paging direction and views fade, both reduced under `prefers-reduced-motion`.

## Third-party notice

`mini-calendar.tsx` is adapted from Untitled UI React `components/application/date-picker/calendar.tsx` and `cell.tsx` (single selection, app tokens, dots for days with events).

MIT License

Copyright (c) 2025 Untitled UI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
