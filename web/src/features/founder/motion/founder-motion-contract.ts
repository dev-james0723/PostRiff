export type FounderMotionStatus = 'integrated' | 'verified' | 'partial' | 'blocked';

export interface FounderMotionContractEntry {
  id: string; label: string; component: string; status: FounderMotionStatus; callSites: string[]; dataSource: string; notes: string;
}

export const FOUNDER_MOTION_CONTRACT: FounderMotionContractEntry[] = [
  {
    "id": "01",
    "label": "Command palette",
    "component": "FounderCommandPalette",
    "status": "integrated",
    "callSites": [
      "features/founder/shell/founder-command-palette.tsx"
    ],
    "dataSource": "Existing permitted navigation and command results",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "02",
    "label": "Collapsible sidebar",
    "component": "FounderSidebar",
    "status": "integrated",
    "callSites": [
      "features/founder/shell/founder-sidebar.tsx"
    ],
    "dataSource": "Existing sidebar state and actual active route",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "03",
    "label": "Morphing navigation island",
    "component": "FounderNavIsland",
    "status": "integrated",
    "callSites": [
      "features/founder/shell/founder-header.tsx"
    ],
    "dataSource": "Verified environment and current section",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "04",
    "label": "Morph select",
    "component": "FounderMorphSelect",
    "status": "integrated",
    "callSites": [
      "features/founder/overview/overview-view.tsx"
    ],
    "dataSource": "Controlled overview period",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "05",
    "label": "Mobile account bottom sheet",
    "component": "FounderMobileAccountSheet",
    "status": "integrated",
    "callSites": [
      "features/founder/shell/founder-header.tsx"
    ],
    "dataSource": "Existing session and permitted navigation",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "06",
    "label": "Expandable contextual action bar",
    "component": "FounderExpandableActionBar",
    "status": "integrated",
    "callSites": [
      "features/founder/actions/customer-actions.tsx"
    ],
    "dataSource": "Server-backed action capabilities",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "07",
    "label": "Dynamic live status",
    "component": "FounderDynamicStatus",
    "status": "integrated",
    "callSites": [
      "features/founder/shell/founder-header.tsx"
    ],
    "dataSource": "Founder query state and actual agent busy state",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "08",
    "label": "Animated toast stack",
    "component": "toast",
    "status": "integrated",
    "callSites": [
      "features/founder/actions/confirm-action-dialog.tsx"
    ],
    "dataSource": "Actual action responses through existing Sonner stack",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "09",
    "label": "Save Saving Saved button",
    "component": "FounderSaveButton",
    "status": "integrated",
    "callSites": [
      "features/founder/settings/contact-policy-form.tsx"
    ],
    "dataSource": "Actual form submission state",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "10",
    "label": "Inline confirmation morph",
    "component": "FounderInlineConfirm",
    "status": "integrated",
    "callSites": [
      "features/founder/overview/attention.tsx"
    ],
    "dataSource": "Explicit incident acknowledgement confirmation",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "11",
    "label": "Slide to confirm",
    "component": "FounderSlideConfirm",
    "status": "integrated",
    "callSites": [
      "features/founder/actions/confirm-action-dialog.tsx"
    ],
    "dataSource": "Existing confirmability and typed permission guards",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "12",
    "label": "Source-to-detail expansion",
    "component": "FounderDetailDialog",
    "status": "integrated",
    "callSites": [
      "features/founder/customers/customer-sheet.tsx"
    ],
    "dataSource": "Paired actual customer ID and retained source row",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "13",
    "label": "Measured modal resizing",
    "component": "FounderStepPanel",
    "status": "integrated",
    "callSites": [
      "features/founder/actions/confirm-action-dialog.tsx"
    ],
    "dataSource": "Measured stage content without keyed form remount",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "14",
    "label": "Animated data grid",
    "component": "FounderAnimatedRows",
    "status": "integrated",
    "callSites": [
      "features/founder/customers/customers-view.tsx"
    ],
    "dataSource": "Server-paged data with keyed Motion table rows",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "15",
    "label": "CRM row selection and details",
    "component": "RecordsTable",
    "status": "integrated",
    "callSites": [
      "features/founder/customers/kit/records-table.tsx"
    ],
    "dataSource": "Mounted customer/workspace table and real selection",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "16",
    "label": "Exact animated numbers",
    "component": "NumberTicker",
    "status": "integrated",
    "callSites": [
      "features/founder/shared/metric-tile.tsx"
    ],
    "dataSource": "Exact count currency and ratio formatter, nulls retained",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "17",
    "label": "Scrubbable line chart",
    "component": "FounderScrubbableTrend",
    "status": "integrated",
    "callSites": [
      "features/founder/overview/trend-chart.tsx"
    ],
    "dataSource": "Returned timestamps and chart selected-point state",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "18",
    "label": "Morphing donut chart",
    "component": "FounderDonutBreakdown",
    "status": "integrated",
    "callSites": [
      "features/founder/overview/attention.tsx"
    ],
    "dataSource": "Observed categorical counts; invalid values labelled",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "19",
    "label": "Insight cards",
    "component": "FounderInsightMotion",
    "status": "integrated",
    "callSites": [
      "features/founder/overview/attention.tsx"
    ],
    "dataSource": "Actual attention items and source actions",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "20",
    "label": "Animated filter chips",
    "component": "FounderFilterChips",
    "status": "integrated",
    "callSites": [
      "features/founder/customers/customers-view.tsx"
    ],
    "dataSource": "Actual individual status and plan filters",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "21",
    "label": "Morphing tooltip",
    "component": "FounderTooltipMotion",
    "status": "integrated",
    "callSites": [
      "features/founder/shared/metric-tile.tsx"
    ],
    "dataSource": "Actual coverage descriptions with accessible triggers",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "22",
    "label": "Bento focus and restore",
    "component": "FounderBentoFocus",
    "status": "integrated",
    "callSites": [
      "features/founder/overview/overview-view.tsx"
    ],
    "dataSource": "Same mounted dashboard card with focus and scroll restore",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "23",
    "label": "Thinking orb",
    "component": "FounderThinkingOrb",
    "status": "integrated",
    "callSites": [
      "features/founder/agent/chat.tsx"
    ],
    "dataSource": "Only a genuinely pending request, visible and motion permitted",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "24",
    "label": "Agent tool chips",
    "component": "FounderToolChips",
    "status": "integrated",
    "callSites": [
      "features/founder/agent/answer.tsx"
    ],
    "dataSource": "Returned toolActivity and actual statuses",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "25",
    "label": "Live task rows",
    "component": "FounderLiveTaskRows",
    "status": "integrated",
    "callSites": [
      "features/founder/agent/chat.tsx"
    ],
    "dataSource": "Observed existing poll results, not invented progress",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "26",
    "label": "Approval cards",
    "component": "FounderApprovalCard",
    "status": "integrated",
    "callSites": [
      "features/founder/actions/confirm-action-dialog.tsx"
    ],
    "dataSource": "Actual action preview and explicit existing confirmation",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "27",
    "label": "Answer reveal and sources",
    "component": "FounderAnswerReveal",
    "status": "integrated",
    "callSites": [
      "features/founder/agent/answer.tsx"
    ],
    "dataSource": "Completed real response and retained source receipts; no fake SSE",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "28",
    "label": "Before and after diff",
    "component": "FounderDiffTable",
    "status": "integrated",
    "callSites": [
      "features/founder/actions/confirm-action-dialog.tsx"
    ],
    "dataSource": "Current and proposed action fields, nulls distinguished",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "29",
    "label": "AI draft editor",
    "component": "FounderAiEditor",
    "status": "integrated",
    "callSites": [
      "features/founder/agent/chat.tsx"
    ],
    "dataSource": "Existing agent transport returns a proposal; explicit stale-safe Apply and Undo",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  },
  {
    "id": "30",
    "label": "Connected process rail",
    "component": "FounderProcessRail",
    "status": "integrated",
    "callSites": [
      "features/founder/actions/confirm-action-dialog.tsx"
    ],
    "dataSource": "Observed actual stage, with one rail-scoped moving bead",
    "notes": "Source integrated. Runtime evidence and production status are recorded separately; this contract is not a claim of live acceptance."
  }
];