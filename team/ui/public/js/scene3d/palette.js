// Colours of the scene: the tokens of base.css (redesign spec 1.1) and the
// tones of the stone model derived from them. Hazard colours mean hazard only;
// copper is "what you act on"; verdigris is a computed route or an available exit.

export const TOKEN = {
  ink0: '#111316',
  ink1: '#171A1E',
  ink2: '#1F2328',
  ink3: '#2A2F36',
  line: '#323840',
  dust1: '#E8E3DA',
  dust2: '#B8B1A5',
  dust3: '#847D72',
  copper: '#C8834F',
  copperStrong: '#E39A62',
  verdigris: '#5FA89E',
  steel: '#7E8B97',
  stone1: '#57534D',
  stone2: '#726D65',
  stone3: '#938C80',
  attention: '#E2A43B',
  danger: '#E0483A',
  unknown: '#A3A7AD',
  noroute: '#F2EFE9',
  chalk: '#D7D1C3',
  lightWarm: '#FFD7A1',
};

/** Tones of the model, all from the stone and ink tokens. */
export const TONE = {
  desk: TOKEN.ink0,
  deskShadow: '#0B0C0E',
  // Sawn stone, a touch cooler and darker than the stone tokens, so that the pale floors of the workings, the
  // people and the signs stand out on it; the lights of the scene warm it back towards --stone-2.
  top: '#6A6862',          // sawn top face of a slab
  topLight: '#8A877F',     // lighter grains and veins of the top face
  topDark: '#4C4A46',      // darker grains of the top face
  sideA: TOKEN.stone1,     // strata of the cut faces, alternating
  sideB: '#6A665F',
  sideC: '#45423E',
  sideHighlight: TOKEN.stone3,
  bottom: TOKEN.ink2,
  wall: '#34322F',         // walls of a carved channel: the darkest stone, darker than any floor
  floor: '#575550',        // floor of a groove without sensors: plain, below the stone
  floorZone: '#DED7C8',    // floor of a controlled working with fresh data: pale sawn stone
  road: '#8C8880',
  roadGlow: '#4A4843',     // the deck of a ramp lit from its own side, whatever its slope
  steel: TOKEN.steel,
  steelDark: '#59626B',
  barricadeLight: '#E4E0D8',
  barricadeDark: '#24272B',
  collar: '#121315',
};
