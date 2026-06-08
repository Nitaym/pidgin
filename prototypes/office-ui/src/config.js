// ─────────────────────────────────────────────────────────────────────────────
// config.js — DATA CATALOGS
// Everything here is plain data. To extend the app (new agent role, new robot
// part, new decoration) you add an entry here; no logic changes required.
// ─────────────────────────────────────────────────────────────────────────────

// Layout constants shared across modules.
export const DESK_W = 128;          // desk width in px (wide)
export const FLOOR_TOP = 188;       // top boundary agents/decor can be dragged to

// ── Agent archetypes ─────────────────────────────────────────────────────────
// Each archetype defines a role and a *default* robot look. Users can then
// freely customize the robot in the editor.
// Each archetype also defines its `desk`: a wood tint + the props on top, so a
// robot's workstation reflects its job. Item types are rendered by world.js:
//   {t:"monitor", v:"code|chart|text|search"}  {t:"mug"}  {t:"papers"}
//   {t:"prop", e:"<emoji>"}  {t:"stickies"}  {t:"books"}
export const AGENT_ARCHETYPES = [
  { id:"researcher", label:"Researcher", role:"Knowledge & Search", emoji:"🔍",
    intro:"Ready to dig in. What do you need?",
    robot:{ chassis:"#3a6ea5", screen:"#0c2c3a", eyes:"dot",     antenna:"light", trim:"#ffd24a" },
    desk:{ tint:"#9c7b46", items:[ {t:"monitor",v:"search"}, {t:"books"}, {t:"papers"} ] } },
  { id:"writer",     label:"Writer",     role:"Content & Copy",     emoji:"✍️",
    intro:"Tell me what to write. I'll make it count.",
    robot:{ chassis:"#7a3a6a", screen:"#1a0a2a", eyes:"happy",   antenna:"ball",  trim:"#ff5a8a" },
    desk:{ tint:"#b89a6a", items:[ {t:"monitor",v:"text"}, {t:"mug"}, {t:"prop",e:"✒️"} ] } },
  { id:"analyst",    label:"Analyst",    role:"Data & Insights",    emoji:"📊",
    intro:"Numbers to stories. What are we analysing?",
    robot:{ chassis:"#3a8a5a", screen:"#0a2a1a", eyes:"visor",   antenna:"dish",  trim:"#7aff9a" },
    desk:{ tint:"#8f9a52", items:[ {t:"monitor",v:"chart"}, {t:"prop",e:"📈"}, {t:"prop",e:"🧮"} ] } },
  { id:"engineer",   label:"Engineer",   role:"Code & Systems",     emoji:"⚙️",
    intro:"Ready to build. What are we shipping?",
    robot:{ chassis:"#8a5a2a", screen:"#2a1a0a", eyes:"cyclops", antenna:"dish",  trim:"#ff7a3a" },
    desk:{ tint:"#9a7340", items:[ {t:"monitor",v:"code"}, {t:"prop",e:"🔧"}, {t:"prop",e:"⚙️"} ] } },
  { id:"planner",    label:"Planner",    role:"Strategy & Tasks",   emoji:"📋",
    intro:"Let's get organised. What's the goal?",
    robot:{ chassis:"#7a2a2a", screen:"#2a0a0a", eyes:"sleepy",  antenna:"light", trim:"#4adcff" },
    desk:{ tint:"#ad8278", items:[ {t:"prop",e:"📋"}, {t:"prop",e:"📅"}, {t:"stickies"} ] } },
];

// Fallback desk for any agent missing one (e.g. older saved data).
export const DEFAULT_DESK = { tint:"#c09858", items:[ {t:"monitor",v:"cursor"}, {t:"mug"}, {t:"papers"} ] };

// ── Robot part catalog ───────────────────────────────────────────────────────
// The customization editor is generated from this. Add a swatch or option and
// it appears automatically.
export const ROBOT_PARTS = {
  // color rows (rendered as swatches)
  colors: [
    { key:"chassis", label:"Chassis", options:["#3a6ea5","#b0563a","#3a8a5a","#8a5a2a","#7a3a6a","#5a5a6a","#c0a040","#cf6a8a"] },
    { key:"screen",  label:"Screen",  options:["#0c2c3a","#1a0a2a","#0a2a1a","#2a1a0a","#102038","#101010"] },
    { key:"trim",    label:"Trim",    options:["#ffd24a","#ff7a3a","#4adcff","#7aff9a","#ff5a8a","#d0d0e0"] },
  ],
  // option rows (rendered as labelled chips)
  picks: [
    { key:"eyes",    label:"Eyes",    options:[
      {id:"dot",label:"Dots"},{id:"happy",label:"Happy"},{id:"visor",label:"Visor"},
      {id:"cyclops",label:"Cyclops"},{id:"sleepy",label:"Sleepy"} ] },
    { key:"antenna", label:"Antenna", options:[
      {id:"light",label:"Light"},{id:"ball",label:"Ball"},{id:"dish",label:"Dish"},{id:"none",label:"None"} ] },
  ],
};

// ── Decoration catalog ───────────────────────────────────────────────────────
export const DECORATIONS = [
  { group:"🌱 Plants", items:[
    { dtype:"plant", emoji:"🌿", label:"Fern" },
    { dtype:"plant", emoji:"🪴", label:"Potted" },
    { dtype:"plant", emoji:"🌵", label:"Cactus" },
    { dtype:"plant", emoji:"🌸", label:"Flower" },
    { dtype:"plant", emoji:"🎋", label:"Bamboo" },
  ]},
  { group:"🪑 Furniture", items:[
    { dtype:"chair", icon:"🪑", label:"Chair",    color:"#c09858", back:"#806028" },
    { dtype:"chair", icon:"🛋️", label:"Armchair", color:"#8b5030", back:"#5a2810" },
  ]},
  { group:"📋 Signs", custom:true, items:[
    { dtype:"sign", icon:"🏢", label:"Office",   text:"MAIN OFFICE" },
    { dtype:"sign", icon:"☕", label:"Lounge",   text:"LOUNGE" },
    { dtype:"sign", icon:"🎯", label:"Strategy", text:"STRATEGY" },
    { dtype:"sign", icon:"🤫", label:"Quiet",    text:"QUIET ZONE" },
    { dtype:"sign", icon:"🚫", label:"No Entry", text:"DO NOT<br>DISTURB" },
  ]},
];

// ── Name pool for new hires ──────────────────────────────────────────────────
export const NAME_POOL = ["Casey","Riley","Sam","Taylor","Avery","Quinn","Drew",
  "Sage","Blake","Reese","Jamie","Skyler","Robin","Pax","Wren","Nova"];

// Canned replies per archetype (prototype chat simulation).
export const REPLIES = {
  researcher:["On it. Here's what I found.","Interesting — a few angles here.","Let me pull together what I know."],
  writer:    ["Here's a draft.","Good brief. First pass incoming.","I'll keep it sharp."],
  analyst:   ["The numbers tell a clear story.","Pattern spotted. Here's the key.","Analysing now..."],
  engineer:  ["Here's my approach.","Checking edge cases first.","Ready to build this."],
  planner:   ["Here are the steps.","Breaking this into phases.","Draft plan ready."],
};
