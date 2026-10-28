import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {FONT} from '../common/fonts';
import {estimateTextHeight, smooth, typeFrames} from '../common/timing';
import {BaseProps, SAFE, t} from '../common/types';
import {CtaCard, Music, withAlpha} from '../common/ui';

/**
 * Format « Notes app » : une note qui se tape toute seule, ligne par ligne.
 * La dernière ligne (le « payoff ») est surlignée, puis la carte CTA arrive.
 */
export type NotesAppProps = BaseProps & {
	title: string;
	items: string[];
	highlightLast?: boolean;
	numbered?: boolean;
};

const INTRO = 14;
const HOLD = 16;
const CTA_HOLD = 80;
const NOTE_YELLOW = '#D9A300';
const ITEM_SIZE = 50;
const TEXT_WIDTH = 1080 - SAFE.left - SAFE.right;

export const notesTimeline = (p: NotesAppProps) => {
	let cursor = INTRO + typeFrames(p.title, 50) + 6;
	const starts: number[] = [];
	const ends: number[] = [];
	for (const item of p.items) {
		starts.push(cursor);
		cursor += typeFrames(item);
		ends.push(cursor);
		cursor += HOLD;
	}
	const ctaStart = cursor + 18;
	return {starts, ends, ctaStart, total: ctaStart + CTA_HOLD};
};

export const NotesApp: React.FC<NotesAppProps> = (p) => {
	const frame = useCurrentFrame();
	const {starts, ends, ctaStart} = notesTimeline(p);
	const titleChars = Math.floor(interpolate(frame, [INTRO, INTRO + typeFrames(p.title, 50)], [0, p.title.length], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}));
	const caretOn = Math.floor(frame / 15) % 2 === 0;

	// Défilement automatique si la note dépasse la zone visible.
	const heights = p.items.map((it) => estimateTextHeight(it, ITEM_SIZE, TEXT_WIDTH - 70) + 34);
	const visibleBudget = 1920 - SAFE.bottom - 520;
	const scrollTarget = (f: number) => {
		let h = 0;
		p.items.forEach((_, i) => {
			if (f >= starts[i]) h += heights[i];
		});
		return Math.max(0, h - visibleBudget);
	};
	const scroll = smooth(scrollTarget, frame, 10);
	const zoom = interpolate(frame, [0, ctaStart], [1, 1.035], {extrapolateRight: 'clamp'});
	const dateLine = t(p.lang, "Aujourd'hui à 21:47", 'Today at 9:47 PM');

	return (
		<AbsoluteFill style={{background: '#F7F5EF', fontFamily: FONT}}>
			<Music src={p.music} />
			<div style={{transform: `scale(${zoom})`, transformOrigin: '50% 30%', height: '100%'}}>
				{/* Barre de navigation générique */}
				<div style={{position: 'absolute', top: SAFE.top - 40, left: SAFE.left, right: SAFE.left, display: 'flex', justifyContent: 'space-between', color: NOTE_YELLOW, fontSize: 44, fontWeight: 600}}>
					<span>‹ {t(p.lang, 'Notes', 'Notes')}</span>
					<span style={{letterSpacing: 4}}>⋯</span>
				</div>
				<div style={{position: 'absolute', top: SAFE.top + 70, left: SAFE.left, right: SAFE.right, transform: `translateY(${-scroll}px)`}}>
					<div style={{fontSize: 28, color: '#9A978F', textAlign: 'center', marginBottom: 36, fontWeight: 500}}>{dateLine}</div>
					<div style={{fontSize: 70, fontWeight: 800, color: '#141414', lineHeight: 1.15, marginBottom: 44}}>
						{p.title.slice(0, titleChars)}
						{frame < starts[0] && caretOn && <Caret />}
					</div>
					{p.items.map((item, i) => {
						if (frame < starts[i]) return null;
						const chars = Math.floor(interpolate(frame, [starts[i], ends[i]], [0, item.length], {extrapolateRight: 'clamp'}));
						const active = frame >= starts[i] && (i === p.items.length - 1 ? frame < ctaStart : frame < starts[i + 1]);
						const isPayoff = p.highlightLast !== false && i === p.items.length - 1;
						const hl = isPayoff ? interpolate(frame, [ends[i] + 2, ends[i] + 14], [0, 100], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 0;
						return (
							<div key={i} style={{display: 'flex', gap: 22, marginBottom: 34, fontSize: ITEM_SIZE, lineHeight: 1.3, color: '#1D1D1D', fontWeight: isPayoff ? 700 : 500}}>
								<span style={{minWidth: 48, color: '#8C8980', fontWeight: 600}}>{p.numbered === false ? '•' : `${i + 1}.`}</span>
								<span style={{flex: 1}}>
									{/* span inline imbriqué : le surlignage suit les retours à la ligne */}
									<span
										style={{
											backgroundImage: `linear-gradient(${withAlpha(p.brand.accent, 0.28)}, ${withAlpha(p.brand.accent, 0.28)})`,
											backgroundRepeat: 'no-repeat',
											backgroundSize: `${hl}% 100%`,
											boxDecorationBreak: 'clone',
											WebkitBoxDecorationBreak: 'clone',
											padding: '0 4px',
										}}
									>
										{item.slice(0, chars)}
									</span>
									{active && caretOn && <Caret />}
								</span>
							</div>
						);
					})}
				</div>
			</div>
			<CtaCard brand={p.brand} lang={p.lang} cta={p.cta} startFrame={ctaStart} />
		</AbsoluteFill>
	);
};

const Caret: React.FC = () => (
	<span style={{display: 'inline-block', width: 4, height: '1em', background: NOTE_YELLOW, marginLeft: 3, verticalAlign: '-0.12em'}} />
);
