// DDS, TGA and BMP textures decoded to RGBA, top row first, at most MAX pixels on a side

const MAX = 512;

export async function decodeTexture(buf) {
  const b = new Uint8Array(buf);
  if (b[0] === 0x44 && b[1] === 0x44 && b[2] === 0x53 && b[3] === 0x20) return shrink(dds(buf));   // "DDS "
  if (b[0] === 0x42 && b[1] === 0x4d) return shrink(await bitmap(buf));                          // "BM"
  return shrink(tga(buf));
}

// --- DDS: DXT1/3/5 and uncompressed RGB(A) -----------------------------------

function dds(buf) {
  const v = new DataView(buf);
  let height = v.getUint32(12, true), width = v.getUint32(16, true);
  const mips = Math.max(1, v.getUint32(28, true));
  const pfFlags = v.getUint32(80, true);
  const fourCC = String.fromCharCode(...new Uint8Array(buf, 84, 4));
  const bits = v.getUint32(88, true);
  const block = fourCC === 'DXT1' ? 8 : fourCC === 'DXT3' || fourCC === 'DXT5' ? 16 : 0;
  if (pfFlags & 0x4 && !block) throw new Error('unsupported DDS ' + fourCC);
  const size = (w, h) => (block ? Math.max(1, Math.ceil(w / 4)) * Math.max(1, Math.ceil(h / 4)) * block
                                : w * h * (bits / 8));
  let off = 128;
  for (let level = 0; level < mips - 1 && Math.max(width, height) > MAX; level++) {
    off += size(width, height);
    width = Math.max(1, width >> 1);
    height = Math.max(1, height >> 1);
  }
  const src = new Uint8Array(buf, off, size(width, height));
  if (block) return { data: dxt(src, width, height, fourCC), width, height };
  const masks = [92, 96, 100, 104].map((o) => v.getUint32(o, true));
  if (!(pfFlags & 0x1)) masks[3] = 0;           // DDPF_ALPHAPIXELS unset: no alpha channel
  return { data: masked(src, width, height, bits / 8, masks), width, height };
}

function rgb565(c, out, i) {
  out[i] = ((c >> 11) & 31) * 255 / 31;
  out[i + 1] = ((c >> 5) & 63) * 255 / 63;
  out[i + 2] = (c & 31) * 255 / 31;
  out[i + 3] = 255;
}

function dxt(src, w, h, kind) {
  const out = new Uint8Array(w * h * 4);
  const pal = new Uint8Array(16), alpha = new Uint8Array(16);
  const bw = Math.max(1, Math.ceil(w / 4)), bh = Math.max(1, Math.ceil(h / 4));
  let p = 0;
  for (let by = 0; by < bh; by++) {
    for (let bx = 0; bx < bw; bx++) {
      let explicit = null;
      if (kind === 'DXT3') {
        explicit = src.subarray(p, p + 8);
        p += 8;
      } else if (kind === 'DXT5') {
        const a0 = src[p], a1 = src[p + 1];
        alpha[0] = a0; alpha[1] = a1;
        for (let k = 1; k < 7; k++) {
          alpha[k + 1] = a0 > a1 ? ((7 - k) * a0 + k * a1) / 7
                       : k < 5 ? ((5 - k) * a0 + k * a1) / 5 : k === 5 ? 0 : 255;
        }
        // DXT5 alpha: 16 3-bit indices in 6 bytes, after the two endpoint bytes
        const lo = src[p + 2] | (src[p + 3] << 8) | (src[p + 4] << 16);
        const hi = src[p + 5] | (src[p + 6] << 8) | (src[p + 7] << 16);
        explicit = new Uint8Array(16);
        for (let k = 0; k < 16; k++) explicit[k] = alpha[k < 8 ? (lo >> (3 * k)) & 7 : (hi >> (3 * (k - 8))) & 7];
        p += 8;
      }
      const c0 = src[p] | (src[p + 1] << 8), c1 = src[p + 2] | (src[p + 3] << 8);
      rgb565(c0, pal, 0);
      rgb565(c1, pal, 4);
      const four = c0 > c1 || kind !== 'DXT1';
      for (let k = 0; k < 3; k++) {
        pal[8 + k] = four ? (2 * pal[k] + pal[4 + k]) / 3 : (pal[k] + pal[4 + k]) / 2;
        pal[12 + k] = four ? (pal[k] + 2 * pal[4 + k]) / 3 : 0;
      }
      pal[11] = 255;
      pal[15] = four ? 255 : 0;
      const idx = src[p + 4] | (src[p + 5] << 8) | (src[p + 6] << 16) | (src[p + 7] << 24);
      p += 8;
      for (let k = 0; k < 16; k++) {
        const x = bx * 4 + (k & 3), y = by * 4 + (k >> 2);
        if (x >= w || y >= h) continue;
        const c = ((idx >>> (2 * k)) & 3) * 4, o = (y * w + x) * 4;
        out[o] = pal[c]; out[o + 1] = pal[c + 1]; out[o + 2] = pal[c + 2]; out[o + 3] = pal[c + 3];
        if (kind === 'DXT3') out[o + 3] = ((explicit[k >> 1] >> ((k & 1) * 4)) & 15) * 17;
        else if (kind === 'DXT5') out[o + 3] = explicit[k];
      }
    }
  }
  return out;
}

function masked(src, w, h, bpp, masks) {
  const out = new Uint8Array(w * h * 4);
  const shift = masks.map((m) => (m ? Math.clz32(1) - Math.clz32(m & -m) : 0));
  const scale = masks.map((m, i) => (m ? 255 / (m >>> shift[i]) : 0));
  for (let i = 0, p = 0; i < w * h; i++, p += bpp) {
    let px = 0;
    for (let k = 0; k < bpp; k++) px |= src[p + k] << (8 * k);
    px >>>= 0;
    for (let c = 0; c < 4; c++) out[i * 4 + c] = masks[c] ? ((px & masks[c]) >>> shift[c]) * scale[c] : 255;
  }
  return out;
}

// --- TGA: true colour, grey and colour-mapped, raw or RLE --------------------

function tga(buf) {
  const b = new Uint8Array(buf);
  const v = new DataView(buf);
  const idLen = b[0], mapType = b[1], type = b[2];
  const mapFirst = v.getUint16(3, true), mapLen = v.getUint16(5, true), mapBits = b[7];
  const width = v.getUint16(12, true), height = v.getUint16(14, true), bits = b[16], desc = b[17];
  let p = 18 + idLen;
  const mapBpp = Math.ceil(mapBits / 8);
  const map = mapType ? b.subarray(p, p + mapLen * mapBpp) : null;
  p += mapType ? mapLen * mapBpp : 0;
  const bpp = Math.ceil(bits / 8), n = width * height;
  // Types 9-11 are RLE: header bit 7 set = repeat one pixel, low 7 bits + 1 = count
  let raw;
  if (type >= 9) {
    raw = new Uint8Array(n * bpp);
    let o = 0;
    while (o < raw.length) {
      const h = b[p++], count = (h & 127) + 1;
      if (h & 128) {
        for (let k = 0; k < count; k++) raw.set(b.subarray(p, p + bpp), o + k * bpp);
        p += bpp;
      } else {
        raw.set(b.subarray(p, p + count * bpp), o);
        p += count * bpp;
      }
      o += count * bpp;
    }
  } else {
    raw = b.subarray(p, p + n * bpp);
  }
  const kind = type & 7;                         // 1 colour-mapped, 2 true colour, 3 grey
  const out = new Uint8Array(n * 4);
  const color = (src, q, nb, o) => {
    if (nb === 2) {
      const c = src[q] | (src[q + 1] << 8);
      out[o] = ((c >> 10) & 31) * 255 / 31; out[o + 1] = ((c >> 5) & 31) * 255 / 31;
      out[o + 2] = (c & 31) * 255 / 31; out[o + 3] = 255;
    } else {
      out[o] = src[q + 2]; out[o + 1] = src[q + 1]; out[o + 2] = src[q];
      out[o + 3] = nb === 4 ? src[q + 3] : 255;
    }
  };
  const topFirst = desc & 0x20;
  for (let i = 0; i < n; i++) {
    const x = i % width, y = Math.floor(i / width);
    const o = ((topFirst ? y : height - 1 - y) * width + x) * 4;
    if (kind === 3) {
      out[o] = out[o + 1] = out[o + 2] = raw[i * bpp];
      out[o + 3] = bpp === 2 ? raw[i * bpp + 1] : 255;
    } else if (kind === 1) {
      const idx = (bpp === 2 ? raw[i * 2] | (raw[i * 2 + 1] << 8) : raw[i]) - mapFirst;
      color(map, idx * mapBpp, mapBpp, o);
    } else {
      color(raw, i * bpp, bpp, o);
    }
  }
  return { data: out, width, height };
}

// --- BMP: the browser decodes it ---------------------------------------------

async function bitmap(buf) {
  const img = await createImageBitmap(new Blob([buf]));
  const c = document.createElement('canvas');
  c.width = img.width;
  c.height = img.height;
  const g = c.getContext('2d');
  g.drawImage(img, 0, 0);
  return { data: new Uint8Array(g.getImageData(0, 0, c.width, c.height).data.buffer), width: c.width, height: c.height };
}

function shrink(t) {
  while (Math.max(t.width, t.height) > MAX) {
    const w = Math.max(1, t.width >> 1), h = Math.max(1, t.height >> 1);
    const out = new Uint8Array(w * h * 4);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        for (let c = 0; c < 4; c++) {
          let s = 0;
          for (let k = 0; k < 4; k++) {
            const sx = Math.min(t.width - 1, x * 2 + (k & 1)), sy = Math.min(t.height - 1, y * 2 + (k >> 1));
            s += t.data[(sy * t.width + sx) * 4 + c];
          }
          out[(y * w + x) * 4 + c] = s / 4;
        }
      }
    }
    t = { data: out, width: w, height: h };
  }
  return t;
}
