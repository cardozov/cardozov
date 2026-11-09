#!/usr/bin/env node
// Writes assets/langs-{dark,light}.svg from the owner's public GitHub repositories.
// Env: GH_USER, GITHUB_TOKEN. Set LANGS_MOCK to a {"top":[...],"repoCount":n} JSON to skip the API.
import { readFile, writeFile } from 'node:fs/promises';

const IGNORED = new Set(['HTML', 'CSS', 'SCSS', 'Dockerfile', 'Shell', 'Makefile', 'Procfile', 'Batchfile']);
const TOP_LIMIT = 6;
const API = 'https://api.github.com';
const MONO = "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace";
const CHAR_WIDTH = 0.6;

// Keep the shared colors in sync with THEMES in scripts/build-assets.py.
const THEMES = {
  dark: {
    card: '#0d1117', border: '#262f3b', text: '#e6edf3', muted: '#8b949e', track: '#1b2430',
    series: ['#3ddc97', '#8b7bff', '#ff7a59', '#4cb8ff', '#f2c14e', '#f472b6'], other: '#4b5563',
  },
  light: {
    card: '#ffffff', border: '#d0d7de', text: '#1f2328', muted: '#59636e', track: '#eef1f4',
    series: ['#12925e', '#5b4be0', '#d4502c', '#1f78c1', '#b58105', '#c43d8b'], other: '#9aa4af',
  },
};

const escapeXml = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const fixed = (value) => Number(value.toFixed(2));

async function github(path) {
  const response = await fetch(`${API}${path}`, {
    headers: {
      Accept: 'application/vnd.github+json',
      'User-Agent': 'profile-languages-card',
      ...(process.env.GITHUB_TOKEN ? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
    },
  });
  if (!response.ok) throw new Error(`GitHub API ${path} returned ${response.status}`);
  return response.json();
}

async function listRepos(user) {
  const repos = [];
  for (let page = 1; ; page += 1) {
    const batch = await github(`/users/${user}/repos?type=owner&per_page=100&page=${page}`);
    repos.push(...batch);
    if (batch.length < 100) return repos;
  }
}

async function collectStats(user) {
  const repos = (await listRepos(user)).filter((repo) => !repo.fork && !repo.archived);
  const totals = new Map();
  for (const repo of repos) {
    const languages = await github(`/repos/${repo.owner.login}/${repo.name}/languages`);
    for (const [name, bytes] of Object.entries(languages)) {
      if (!IGNORED.has(name)) totals.set(name, (totals.get(name) ?? 0) + bytes);
    }
  }

  const sorted = [...totals].sort((a, b) => b[1] - a[1]);
  const sum = sorted.reduce((acc, [, bytes]) => acc + bytes, 0);
  if (sum === 0) throw new Error(`No language data found for ${user}`);

  const toPct = (bytes) => (bytes / sum) * 100;
  const top = sorted.slice(0, TOP_LIMIT).map(([name, bytes]) => ({ name, pct: toPct(bytes) }));
  const rest = sorted.slice(TOP_LIMIT).reduce((acc, [, bytes]) => acc + bytes, 0);
  if (rest > 0) top.push({ name: 'Other', pct: toPct(rest) });
  return { top, repoCount: repos.length };
}

function renderCard(theme, stats, fontCss, date) {
  const W = 960;
  const H = 196;
  const cardY = 44;
  const cardH = 150;
  const barX = 25;
  const barY = 72;
  const barW = 910;
  const barH = 14;
  const columnW = barW / 4;
  const total = stats.top.reduce((acc, item) => acc + item.pct, 0);

  let colorIndex = 0;
  const items = stats.top.map((item) => ({
    ...item,
    color: item.name === 'Other' ? theme.other : theme.series[colorIndex++ % theme.series.length],
  }));

  let cursor = barX;
  const segments = items.map((item, index) => {
    const width = (item.pct / total) * barW;
    const drawn = index === items.length - 1 ? width : Math.max(width - 2, 1);
    const rect = `<rect x="${fixed(cursor)}" y="${barY}" width="${fixed(drawn)}" height="${barH}" fill="${item.color}"/>`;
    cursor += width;
    return rect;
  });

  const legend = items.map((item, index) => {
    const column = index % 4;
    const row = Math.floor(index / 4);
    const x = barX + column * columnW;
    const y = 124 + row * 36;
    const delay = (1.1 + index * 0.08).toFixed(2);
    const pctRight = fixed(x + columnW - 24);
    return (
      `<g class="fade" style="animation-delay:${delay}s">` +
      `<circle cx="${fixed(x + 5)}" cy="${y - 5}" r="5" fill="${item.color}"/>` +
      `<text class="m" x="${fixed(x + 20)}" y="${y}" font-size="14" fill="${theme.text}">${escapeXml(item.name)}</text>` +
      `<text class="m" x="${pctRight}" y="${y}" font-size="14" text-anchor="end" fill="${theme.muted}">${item.pct.toFixed(1)}%</text>` +
      '</g>'
    );
  });

  const repoWord = stats.repoCount === 1 ? 'repo' : 'repos';
  const css =
    `.m{font-family:${MONO}}` +
    '@media (prefers-reduced-motion:reduce){*{animation:none!important}}' +
    '@keyframes grow{from{transform:scaleX(0)}}' +
    `.grow{transform-origin:${barX}px 0;animation:grow 1.2s cubic-bezier(.2,.7,.2,1) .3s both}` +
    '@keyframes fade{from{opacity:0}}' +
    '.fade{animation:fade .5s ease-out both}';

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img">` +
    `<title>Most used languages across ${stats.repoCount} ${repoWord}</title>` +
    `<style>${fontCss}${css}</style>` +
    `<defs><clipPath id="bar"><rect x="${barX}" y="${barY}" width="${barW}" height="${barH}" rx="7"/></clipPath></defs>` +
    `<text class="m" x="4" y="26" font-size="16" fill="${theme.text}">` +
    `<tspan fill="${theme.series[0]}" font-weight="700">$</tspan> cat languages.log</text>` +
    `<text class="m" x="956" y="26" font-size="13" text-anchor="end" fill="${theme.muted}">${stats.repoCount} ${repoWord} · updated ${date}</text>` +
    `<rect x="1" y="${cardY}" width="958" height="${cardH}" rx="12" fill="${theme.card}" stroke="${theme.border}"/>` +
    `<rect x="${barX}" y="${barY}" width="${barW}" height="${barH}" rx="7" fill="${theme.track}"/>` +
    `<g clip-path="url(#bar)"><g class="grow">${segments.join('')}</g></g>` +
    legend.join('') +
    '</svg>\n'
  );
}

async function main() {
  const stats = process.env.LANGS_MOCK
    ? JSON.parse(process.env.LANGS_MOCK)
    : await collectStats(requireUser());
  const fontCss = (await readFile(new URL('./fonts.css', import.meta.url), 'utf8')).replace(/\n/g, '');
  const date = new Date().toISOString().slice(0, 10);

  for (const [name, theme] of Object.entries(THEMES)) {
    await writeFile(
      new URL(`../assets/langs-${name}.svg`, import.meta.url),
      renderCard(theme, stats, fontCss, date),
    );
  }
  console.log(`Wrote language cards for ${stats.repoCount} repos: ${stats.top.map((item) => item.name).join(', ')}`);
}

function requireUser() {
  const user = process.env.GH_USER;
  if (!user) throw new Error('GH_USER is required');
  return user;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
