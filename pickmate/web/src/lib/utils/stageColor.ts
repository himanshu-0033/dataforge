const colors: Record<string, string> = {
  ready: '#276449',
  awaiting_confirmation: '#eadba5',
  committed: '#276449',
  cancelled: '#e8e8e4',
  resolving: '#deded7',
  looking_up: '#deded7',
};

export function solidStageColor(stage: string) { return colors[stage] ?? '#e8e8e4'; }
export function readableTextColor(hex: string) {
  const rgb = hex.replace('#', '').match(/.{2}/g)!.map(value => {
    const channel = parseInt(value, 16) / 255;
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
  });
  const luminance = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
  return luminance > .179 ? '#20241f' : '#ffffff';
}
