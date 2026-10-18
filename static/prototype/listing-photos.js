const listingPhotos = {
  location(row, className = '') {
    const address = document.createElement('span');
    address.className = 'listing-address ' + className;
    const parts = String(row.location || '').split(/\s*[\u00b7\u2022|]\s*/u).filter(Boolean);
    if (parts.length > 1 && /^(?:[\d,]+[- ]zimmer[- ]wohnung|wohnung|apartment|studio)$/i.test(parts[0])) parts.shift();
    for (const part of parts) {
      const line = document.createElement('span');
      line.textContent = part;
      address.append(line);
    }
    return address;
  },
  create(row, className = '') {
    const frame = document.createElement('span');
    frame.className = 'listing-photo ' + className;
    const missing = () => {
      frame.replaceChildren();
      frame.textContent = 'Photo unavailable';
    };
    let url;
    try {
      url = new URL(row.image_url);
      const wgPhoto = ['www.wg-gesucht.de', 'img.wg-gesucht.de'].includes(url.hostname) && url.pathname.startsWith('/media/up/');
      const omPhoto = url.hostname === 'media.ohne-makler.net' ||
        (url.hostname === 'www.ohne-makler.net' && /^\/immobilie\/\d+\/picture\//.test(url.pathname));
      const hc24Photo = url.hostname === 'hc24-media-new.s3.eu-central-1.amazonaws.com' &&
        /^\/hcwu\/\d+_\d+\.jpg$/.test(url.pathname) &&
        url.pathname.startsWith('/hcwu/' + String(row.id).replace(/^hc24:wu/, '') + '_') &&
        /^hc24:wu\d+$/.test(String(row.id));
      if (url.protocol !== 'https:' || url.username || url.password || !(wgPhoto || omPhoto || hc24Photo)) throw Error('Not a listing photo');
    } catch {
      missing();
      return frame;
    }
    const image = document.createElement('img');
    image.alt = 'Listing photo for ' + row.title;
    image.loading = 'lazy';
    image.decoding = 'async';
    image.referrerPolicy = 'no-referrer';
    image.addEventListener('error', missing, {once: true});
    image.src = url.href;
    frame.append(image);
    return frame;
  },
  async hydrate(rows) {
    if (!rows.some(row => !row.image_url && !String(row.id).startsWith('demo'))) return;
    try {
      const response = await fetch('/api/photos', {cache: 'no-store', signal: AbortSignal.timeout(45000)});
      if (!response.ok) return;
      const photos = await response.json();
      for (const row of rows) {
        if (!row.image_url && typeof photos[row.id] === 'string') row.image_url = photos[row.id];
      }
      document.querySelectorAll('[data-photo-id]').forEach(frame => {
        const row = rows.find(row => String(row.id) === frame.dataset.photoId);
        if (row?.image_url) frame.replaceWith(listingPhotos.forRow(row, frame.dataset.photoClass));
      });
    } catch {
      // Missing photos must not interrupt apartment comparisons.
    }
  },
  forRow(row, className = '') {
    const frame = this.create(row, className);
    frame.dataset.photoId = String(row.id);
    frame.dataset.photoClass = className;
    return frame;
  }
};
