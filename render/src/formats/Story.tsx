import React from 'react';
import {AbsoluteFill, interpolate, OffthreadVideo, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT} from '../common/fonts';
import {BaseProps, FPS, SAFE, t} from '../common/types';
import {AppIcon, MockScreen, MockScreenView, Music, PhoneFrame, ScreenImage, withAlpha} from '../common/ui';

/**
 * Format « story » : une suite de plans, produite par le module production pour les formats à plans
 * (app-story, ai-hook-demo, ugc-ai, demo-recording).
 *
 * - clip      : vidéo plein écran (plan IA, personne qui parle, démo horizontale), son gardé si `audio`
 * - screen    : capture de l'app dans un iPhone, avec un léger mouvement (`mock` = écran factice de démo)
 * - recording : enregistrement d'écran de l'app dans un iPhone
 * - card      : carte texte aux couleurs de la marque
 * - end       : carte de fin (icône, appel à l'action, store)
 *
 * `text` s'incruste en haut (**mot** = couleur de la marque) ; `subtitle` s'affiche en sous-titres,
 * par groupes de mots, au-dessus de la zone masquée par TikTok. Fondu court entre deux plans ; des plans
 * screen/recording qui se suivent gardent le même iPhone et seul l'écran change.
 * `duration` et `trimBefore` sont en secondes ; le module production calcule la même chronologie
 * (engine/loopcast/production/plan.py) pour rattacher un défaut du contrôle qualité à un plan.
 */
export type StoryShot = {
	kind: 'clip' | 'screen' | 'recording' | 'card' | 'end';
	duration: number; // secondes
	src?: string; // chemin dans public/
	mock?: MockScreen;
	trimBefore?: number; // secondes sautées au début de la vidéo
	audio?: boolean; // garder le son du clip
	fit?: 'cover' | 'contain';
	text?: string;
	subtitle?: string;
};
export type StoryProps = BaseProps & {shots: StoryShot[]};

const FADE = 8; // frames de fondu entre deux plans
const PHONE_W = 640;
const PHONE_TOP = 410;
const TEXT_W = 1080 - SAFE.left - SAFE.right;
const SUB_BOTTOM = SAFE.bottom + 36; // bas des sous-titres, au-dessus de la légende TikTok
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

export const storyTimeline = (p: Pick<StoryProps, 'shots'>) => {
	const starts: number[] = [];
	const lengths: number[] = [];
	let cursor = 0;
	for (const s of p.shots) {
		const n = Math.max(1, Math.round(s.duration * FPS));
		starts.push(cursor);
		lengths.push(n);
		cursor += n;
	}
	return {starts, lengths, total: Math.max(1, cursor)};
};

const isPhone = (s: StoryShot) => s.kind === 'screen' || s.kind === 'recording';

/** Les plans d'écran qui se suivent partagent le même iPhone : seul l'écran change. */
const segments = (shots: StoryShot[]): number[][] => {
	const out: number[][] = [];
	shots.forEach((s, i) => {
		const last = out[out.length - 1];
		if (last && isPhone(s) && isPhone(shots[last[0]])) last.push(i);
		else out.push([i]);
	});
	return out;
};

type Item = {shot: StoryShot; from: number; len: number};

export const Story: React.FC<StoryProps> = (p) => {
	const {starts, lengths} = storyTimeline(p);
	const segs = segments(p.shots);
	return (
		<AbsoluteFill style={{background: '#0E0E12', fontFamily: FONT}}>
			<Music src={p.music} />
			{segs.map((seg, k) => {
				const from = starts[seg[0]];
				const end = seg[seg.length - 1];
				const len = starts[end] + lengths[end] - from;
				const items: Item[] = seg.map((i) => ({shot: p.shots[i], from: starts[i] - from, len: lengths[i]}));
				return (
					// Chaque segment déborde de FADE frames sous le suivant, qui apparaît en fondu par-dessus.
					<Sequence key={k} from={from} durationInFrames={len + (k < segs.length - 1 ? FADE : 0)}>
						<FadeIn enabled={k > 0}>
							{isPhone(items[0].shot) ? <PhoneStage items={items} p={p} len={len} /> : <Single shot={items[0].shot} p={p} len={len} />}
						</FadeIn>
					</Sequence>
				);
			})}
		</AbsoluteFill>
	);
};

const FadeIn: React.FC<{enabled: boolean; children: React.ReactNode}> = ({enabled, children}) => {
	const frame = useCurrentFrame();
	const opacity = enabled ? interpolate(frame, [0, FADE], [0, 1], clamp) : 1;
	const settle = enabled ? interpolate(frame, [0, FADE + 4], [1.04, 1], clamp) : 1;
	return <AbsoluteFill style={{opacity, transform: `scale(${settle})`}}>{children}</AbsoluteFill>;
};

const Single: React.FC<{shot: StoryShot; p: StoryProps; len: number}> = ({shot, p, len}) => (
	<AbsoluteFill>
		{shot.kind === 'clip' && <ClipShot shot={shot} p={p} len={len} />}
		{shot.kind === 'card' && <CardShot shot={shot} p={p} len={len} />}
		{shot.kind === 'end' && <EndShot shot={shot} p={p} len={len} />}
		{shot.subtitle && shot.kind !== 'end' && <Subtitles text={shot.subtitle} len={len} accent={p.brand.accent} />}
	</AbsoluteFill>
);

// ---------- Les plans ----------

const ClipShot: React.FC<{shot: StoryShot; p: StoryProps; len: number}> = ({shot, p, len}) => {
	const frame = useCurrentFrame();
	const contain = shot.fit === 'contain';
	const push = interpolate(frame, [0, len], [1, 1.05]); // lente avancée : l'image ne fige jamais
	const volume = (f: number) => interpolate(f, [len - 2, len + FADE], [1, 0], clamp);
	return (
		<AbsoluteFill style={{background: contain ? brandGradient(p.brand.accent) : '#000'}}>
			<AbsoluteFill style={{transform: `scale(${push})`, justifyContent: 'center'}}>
				{shot.src && (
					<OffthreadVideo
						src={staticFile(shot.src)}
						trimBefore={Math.round((shot.trimBefore ?? 0) * FPS)}
						muted={!shot.audio}
						volume={shot.audio ? volume : 0}
						style={{width: '100%', height: contain ? 'auto' : '100%', objectFit: contain ? 'contain' : 'cover'}}
					/>
				)}
			</AbsoluteFill>
			{/* Voile haut et bas : le texte reste lisible sur n'importe quelle image. */}
			<AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(0,0,0,0.42) 0%, rgba(0,0,0,0) 30%, rgba(0,0,0,0) 58%, rgba(0,0,0,0.5) 100%)'}} />
			{shot.text && <BoxedText text={shot.text} accent={p.brand.accent} top={SAFE.top + 70} />}
		</AbsoluteFill>
	);
};

/** Un iPhone qui entre une fois puis avance lentement ; ses écrans (captures, enregistrements) se succèdent en fondu. */
const PhoneStage: React.FC<{items: Item[]; p: StoryProps; len: number}> = ({items, p, len}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const enter = spring({frame, fps, config: {damping: 16, mass: 0.8}});
	const drift = interpolate(frame, [0, len], [0, 1]);
	const last = items.length - 1;
	return (
		<AbsoluteFill style={{background: `linear-gradient(180deg, ${withAlpha(p.brand.accent, 0.22)} 0%, #F3F3F7 52%, #ECECF2 100%)`}}>
			{items.map((it, j) =>
				it.shot.text ? (
					<Sequence key={j} from={it.from} durationInFrames={it.len}>
						<Caption text={it.shot.text} accent={p.brand.accent} len={it.len} last={j === last} />
					</Sequence>
				) : null,
			)}
			<div
				style={{
					position: 'absolute',
					top: PHONE_TOP,
					left: 0,
					right: 0,
					display: 'flex',
					justifyContent: 'center',
					transformOrigin: '50% 25%',
					transform: `translateY(${(1 - enter) * 140 - drift * 22}px) scale(${0.95 + enter * 0.05 + drift * 0.03})`,
				}}
			>
				<PhoneFrame width={PHONE_W}>
					{items.map((it, j) => (
						<Sequence key={j} from={it.from} durationInFrames={it.len + (j < last ? FADE : 0)}>
							<ScreenLayer shot={it.shot} p={p} len={it.len} fadeIn={j > 0} />
						</Sequence>
					))}
				</PhoneFrame>
			</div>
			{items.map((it, j) =>
				it.shot.subtitle ? (
					<Sequence key={j} from={it.from} durationInFrames={it.len}>
						<Subtitles text={it.shot.subtitle} len={it.len} accent={p.brand.accent} />
					</Sequence>
				) : null,
			)}
		</AbsoluteFill>
	);
};

/** L'écran du téléphone : enregistrement d'écran, capture (lente avancée vers le haut de l'écran) ou écran factice. */
const ScreenLayer: React.FC<{shot: StoryShot; p: StoryProps; len: number; fadeIn: boolean}> = ({shot, p, len, fadeIn}) => {
	const frame = useCurrentFrame();
	const opacity = fadeIn ? interpolate(frame, [0, FADE], [0, 1], clamp) : 1;
	const zoom = shot.kind === 'recording' ? 1 : interpolate(frame, [0, len], [1, 1.04]);
	return (
		<AbsoluteFill style={{opacity, background: '#FFF'}}>
			<AbsoluteFill style={{transform: `scale(${zoom})`, transformOrigin: '50% 0%'}}>
				{shot.kind === 'recording' && shot.src ? (
					<OffthreadVideo
						src={staticFile(shot.src)}
						trimBefore={Math.round((shot.trimBefore ?? 0) * FPS)}
						muted
						style={{width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top'}}
					/>
				) : shot.src ? (
					<ScreenImage src={shot.src} />
				) : shot.mock ? (
					<MockScreenView screen={shot.mock} brand={p.brand} width={PHONE_W} />
				) : null}
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

/** Légende au-dessus du téléphone : elle glisse en place et s'efface juste avant la suivante. */
const Caption: React.FC<{text: string; accent: string; len: number; last: boolean}> = ({text, accent, len, last}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const appear = spring({frame: frame - 2, fps, config: {damping: 14}});
	const leave = last ? 0 : interpolate(frame, [len - 5, len], [0, 1], clamp);
	return (
		<div
			style={{
				position: 'absolute',
				top: SAFE.top + 10,
				left: SAFE.left,
				width: TEXT_W,
				fontSize: 64,
				fontWeight: 800,
				color: '#121216',
				lineHeight: 1.12,
				letterSpacing: -1,
				opacity: appear * (1 - leave),
				transform: `translateY(${(1 - appear) * -24}px)`,
			}}
		>
			<RichText text={text} accent={accent} />
		</div>
	);
};

const CardShot: React.FC<{shot: StoryShot; p: StoryProps; len: number}> = ({shot, p, len}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const list = words(shot.text ?? '');
	const zoom = interpolate(frame, [0, len], [1, 1.06]);
	const size = list.length > 9 ? 84 : 100;
	return (
		<AbsoluteFill style={{background: brandGradient(p.brand.accent), justifyContent: 'center', padding: `0 ${SAFE.right}px 0 ${SAFE.left + 10}px`}}>
			<div style={{transform: `scale(${zoom})`, transformOrigin: '0% 50%', display: 'flex', flexWrap: 'wrap', gap: '4px 22px', marginTop: -140}}>
				{list.map((w, i) => {
					const s = spring({frame: frame - i * 4, fps, config: {damping: 12, mass: 0.5}});
					return (
						<span
							key={i}
							style={{
								fontSize: size,
								fontWeight: 900,
								lineHeight: 1.08,
								letterSpacing: -2,
								color: '#FFFFFF',
								opacity: s,
								transform: `translateY(${(1 - s) * 50}px) scale(${0.86 + s * 0.14})`,
								display: 'inline-block',
								textShadow: '0 6px 30px rgba(0,0,0,0.35)',
							}}
						>
							<WordView word={w} accent={lighten(p.brand.accent)} />
						</span>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};

const EndShot: React.FC<{shot: StoryShot; p: StoryProps; len: number}> = ({shot, p, len}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const pop = spring({frame, fps, config: {damping: 12, mass: 0.7}});
	const rise = (delay: number) => spring({frame: frame - delay, fps, config: {damping: 15}});
	const glow = interpolate(frame, [0, len], [0, 1]);
	const storeLine = p.brand.storeLine ?? t(p.lang, "Gratuit sur l'App Store et Google Play", 'Free on the App Store & Google Play');
	const line = (delay: number): React.CSSProperties => ({opacity: rise(delay), transform: `translateY(${(1 - rise(delay)) * 40}px)`});
	return (
		<AbsoluteFill
			style={{
				background: `radial-gradient(circle at 50% ${38 - glow * 6}%, ${withAlpha(p.brand.accent, 0.75)} 0%, #121218 ${62 + glow * 8}%)`,
				justifyContent: 'center',
				alignItems: 'center',
				textAlign: 'center',
				// Marges égales des deux côtés : centré, et rien sous la colonne de boutons TikTok à droite.
				padding: `${SAFE.top}px ${SAFE.right}px ${SAFE.bottom}px ${SAFE.right}px`,
			}}
		>
			<div style={{transform: `scale(${0.6 + pop * 0.4 + glow * 0.04})`, opacity: pop}}>
				<AppIcon brand={p.brand} size={250} />
			</div>
			<div style={{...line(5), fontSize: 92, fontWeight: 900, color: '#FFF', marginTop: 52, letterSpacing: -2}}>{p.brand.name}</div>
			<div style={{...line(9), fontSize: 60, fontWeight: 800, color: '#FFF', marginTop: 24, lineHeight: 1.15}}>{shot.text || p.cta}</div>
			<div style={{...line(13), fontSize: 36, fontWeight: 600, color: 'rgba(255,255,255,0.78)', marginTop: 28}}>{storeLine}</div>
			{p.brand.handle && <div style={{...line(16), fontSize: 34, fontWeight: 600, color: 'rgba(255,255,255,0.6)', marginTop: 14}}>{p.brand.handle}</div>}
		</AbsoluteFill>
	);
};

// ---------- Textes ----------

type Part = {text: string; accent: boolean};
type Word = Part[];

/**
 * « Choisis **3 habitudes**, pas 15 » → mots ; ce qui est entre ** ** prend la couleur de la marque.
 * Une ponctuation collée au marqueur reste collée à son mot (« habitudes, »).
 */
const words = (text: string): Word[] => {
	const out: Word[] = [];
	let glue = false;
	text.split('**').forEach((segment, k) => {
		for (const token of segment.split(/(\s+)/)) {
			if (!token) continue;
			if (/^\s+$/.test(token)) {
				glue = false;
				continue;
			}
			const part = {text: token, accent: k % 2 === 1};
			if (glue && out.length) out[out.length - 1].push(part);
			else out.push([part]);
			glue = true;
		}
	});
	return out;
};

const WordView: React.FC<{word: Word; accent: string}> = ({word, accent}) => (
	<>
		{word.map((part, j) => (
			<span key={j} style={{color: part.accent ? accent : undefined}}>
				{part.text}
			</span>
		))}
	</>
);

const RichText: React.FC<{text: string; accent: string}> = ({text, accent}) => (
	<>
		{words(text).map((w, i) => (
			<React.Fragment key={i}>
				{i > 0 && ' '}
				<WordView word={w} accent={accent} />
			</React.Fragment>
		))}
	</>
);

/** Texte en boîtes blanches ligne à ligne (style natif TikTok), lisible sur n'importe quelle vidéo. */
const BoxedText: React.FC<{text: string; accent: string; top: number}> = ({text, accent, top}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = spring({frame: frame - 2, fps, config: {damping: 13, mass: 0.6}});
	return (
		<div style={{position: 'absolute', top, left: SAFE.left, width: TEXT_W, opacity: s, transform: `translateY(${(1 - s) * -30}px) scale(${0.94 + s * 0.06})`, transformOrigin: '0 0'}}>
			<span
				style={{
					background: '#FFFFFF',
					color: '#111114',
					fontSize: 66,
					fontWeight: 800,
					lineHeight: 1.36,
					letterSpacing: -1,
					padding: '4px 22px',
					borderRadius: 18,
					boxDecorationBreak: 'clone',
					WebkitBoxDecorationBreak: 'clone',
				}}
			>
				<RichText text={text} accent={accent} />
			</span>
		</div>
	);
};

/** Découpe en groupes de 2 à 4 mots (coupure aux ponctuations), affichés tour à tour. */
const chunks = (text: string, maxChars = 22, maxWords = 4): string[] => {
	const out: string[] = [];
	let cur: string[] = [];
	for (const w of text.split(/\s+/).filter(Boolean)) {
		const next = [...cur, w].join(' ');
		if (cur.length > 0 && (next.length > maxChars || cur.length >= maxWords)) {
			out.push(cur.join(' '));
			cur = [];
		}
		cur.push(w);
		if (/[.!?…;:,]$/.test(w) && cur.length > 1) {
			out.push(cur.join(' '));
			cur = [];
		}
	}
	if (cur.length) out.push(cur.join(' '));
	return out;
};

const Subtitles: React.FC<{text: string; len: number; accent: string}> = ({text, len, accent}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const parts = chunks(text);
	const lead = 3;
	const span = Math.max(parts.length, len - lead - 4);
	const weights = parts.map((c) => c.length + 6);
	const total = weights.reduce((a, b) => a + b, 0);
	let cursor = lead;
	let current = -1;
	let startedAt = 0;
	parts.forEach((_, i) => {
		const n = (weights[i] / total) * span;
		if (frame >= cursor) {
			current = i;
			startedAt = cursor;
		}
		cursor += n;
	});
	if (current < 0 || frame >= len) return null;
	const pop = spring({frame: frame - startedAt, fps, config: {damping: 14, mass: 0.5}});
	return (
		// Centrés dans la zone sûre (pas sur l'image entière) : jamais sous la colonne de boutons TikTok.
		<AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', padding: `0 ${SAFE.right}px ${SUB_BOTTOM}px ${SAFE.left}px`}}>
			<div
				style={{
					maxWidth: TEXT_W,
					textAlign: 'center',
					fontSize: 68,
					fontWeight: 900,
					lineHeight: 1.14,
					color: '#FFFFFF',
					// Contour noir dessiné sous le blanc : lisible sur fond clair comme sur une vidéo.
					WebkitTextStroke: '10px #000000',
					paintOrder: 'stroke fill',
					textShadow: `0 6px 24px rgba(0,0,0,0.45), 0 0 2px ${withAlpha(accent, 0.2)}`,
					transform: `scale(${0.82 + pop * 0.18})`,
					wordSpacing: 8,
				}}
			>
				{parts[current]}
			</div>
		</AbsoluteFill>
	);
};

// ---------- Couleurs ----------

const brandGradient = (accent: string) => `linear-gradient(160deg, ${withAlpha(accent, 0.95)} 0%, #121218 78%)`;

/** L'accent éclairci, pour un mot en couleur sur fond sombre ou coloré. */
const lighten = (hex: string) => {
	const h = hex.replace('#', '');
	const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
	const mix = (c: number) => Math.round(c + (255 - c) * 0.55);
	return `rgb(${mix((n >> 16) & 255)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`;
};

// ---------- Démo (Studio) ----------

export const storyDemo: StoryProps = {
	lang: 'fr',
	brand: {name: 'Habitudo', accent: '#5B5BF7', handle: '@habitudo'},
	cta: 'Lance ta série ce soir',
	shots: [
		{kind: 'card', duration: 2.4, text: 'Tu abandonnes tes **résolutions** au bout de 3 jours ?'},
		{
			kind: 'screen',
			duration: 3.2,
			text: 'Choisis **3 habitudes**, pas 15',
			subtitle: 'Commence petit : trois habitudes, pas plus.',
			mock: {kind: 'list', title: 'Aujourd’hui', items: [{label: 'Lire 10 pages', done: true}, {label: 'Marcher 20 min', done: true}, {label: 'Pas d’écran au lit'}]},
		},
		{
			kind: 'screen',
			duration: 3.0,
			text: 'Coche-les chaque soir',
			subtitle: 'Un geste par soir, et ta série grimpe.',
			mock: {kind: 'stat', title: 'Série', value: '21', label: 'jours d’affilée 🔥'},
		},
		{kind: 'end', duration: 2.6},
	],
};
