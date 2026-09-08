const colors: Record<string, string> = {
  ready: '#2b2e42',
  awaiting_confirmation: '#d9202a',
  committed: '#2b2e42',
  cancelled: '#f4f5f1',
  resolving: '#f4f5f1',
  looking_up: '#f4f5f1',
};

export function solidStageColor(stage: string) { return colors[stage] ?? '#f4f5f1'; }
export function readableTextColor(hex: string) {
  const rgb = hex.replace('#', '').match(/.{2}/g)!.map(value => {
    const channel = parseInt(value, 16) / 255;
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
  });
  const luminance = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
  return luminance > .179 ? '#2b2e42' : '#f4f5f1';
}
