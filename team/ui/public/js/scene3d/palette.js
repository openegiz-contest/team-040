// Colours of the scene: the tokens of base.css (redesign spec 1.1 and the
// colour roles of the clarity pass) and the tones of the stone model derived
// from them. Hazard colours mean hazard only; selection is a chalk-white double
// ring with the warm work light; the light steel of the primary action marks
// what a decision option would act on; verdigris is a computed route or an
// available exit. Copper is not used in the scene.

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
  /** Selection: the chalk-white double ring. */
  select: '#F2EFE9',
  /** The primary action (--action): the zones and people a hovered decision option covers. */
  action: '#AEBBC7',
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

/**
 * The surroundings of the model (environment.js): the rock massif the slabs are cut from, the light, the depth and
 * the lamps of the workings. Stone and ink only, a little cooler and darker than the slabs, so the model stays in
 * front; the ore veins are the dull tones of the copper minerals, thin and never on a floor, where the hazard
 * colours live. Nothing here is a state.
 */
export const ENV = {
  // The massif: strata of a cool grey rock, darker than the slabs, and its sawn cut edges.
  rockA: '#46494C',
  rockB: '#505255',
  rockC: '#393C3F',
  rockD: '#5A5957',
  rockE: '#474D4B',        // a greenish bed (chloritic)
  rockF: '#544F4A',        // a warmer bed (iron-stained)
  rockParting: '#303336',  // thin partings between beds
  rockSeam: '#6E6A62',
  cutEdge: '#8F897E',
  // Copper ore in the rock: chalcopyrite (dull brass), bornite (purple-bronze tarnish), malachite (green streaks).
  chalcopyrite: '#9A8650',
  bornite: '#6B5260',
  malachite: '#4F7F66',
  // The scene behind the model: a cool graphite with a soft vignette (high quality), or its plain tone (light quality).
  backCentre: '#181B20',
  backEdge: '#08090B',
  back: '#121418',
  // The light: a warm work light as the key, a cool sky over a dark ground, a cool rim from behind.
  key: '#FFEBD8',
  sky: '#CDD6E0',
  ground: '#15181C',
  rim: '#9FB4CA',
  // The lamps of the workings: a dark steel post and a warm lit lens.
  lampPost: '#2B2E33',
  lampLens: '#FFD9A0',
};
