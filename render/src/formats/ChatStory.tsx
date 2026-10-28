import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT} from '../common/fonts';
import {estimateTextHeight, readFrames, smooth} from '../common/timing';
import {BaseProps, SAFE, t} from '../common/types';
import {CtaCard, Music} from '../common/ui';

/**
 * Format « conversation » : une discussion de messagerie (interface générique, sans marque)
 * qui raconte le problème puis la solution (l'app).
 */
export type ChatMessage = {from: 'me' | 'them'; text: string};
export type ChatStoryProps = BaseProps & {
	contactName: string;
	messages: ChatMessage[];
};

const TYPING = 24;
const BUBBLE_SIZE = 44;
const BUBBLE_MAX_W = 720;
const CTA_HOLD = 85;

export const chatTimeline = (p: ChatStoryProps) => {
	let cursor = 12;
	const typingAt: number[] = [];
	const bubbleAt: number[] = [];
	for (const m of p.messages) {
		typingAt.push(cursor);
		const at = m.from === 'them' ? cursor + TYPING : cursor + 8;
		bubbleAt.push(at);
		cursor = at + readFrames(m.text);
	}
	const ctaStart = cursor + 6;
	return {typingAt, bubbleAt, ctaStart, total: ctaStart + CTA_HOLD};
};

export const ChatStory: React.FC<ChatStoryProps> = (p) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const {typingAt, bubbleAt, ctaStart} = chatTimeline(p);

	const heights = p.messages.map((m) => estimateTextHeight(m.text, BUBBLE_SIZE, BUBBLE_MAX_W - 64, 1.28) + 48 + 18);
	const budget = 1920 - SAFE.bottom - 200 - SAFE.top - 160;
	const scrollTarget = (f: number) => {
		let h = 0;
		p.messages.forEach((m, i) => {
			if (f >= bubbleAt[i]) h += heights[i];
			else if (m.from === 'them' && f >= typingAt[i]) h += 110;
		});
		return Math.max(0, h - budget);
	};
	const scroll = smooth(scrollTarget, frame, 8);
	const initial = p.contactName.trim().charAt(0).toUpperCase();

	return (
		<AbsoluteFill style={{background: '#0E0E12', fontFamily: FONT}}>
			<Music src={p.music} />
			{/* En-tête */}
			<div
				style={{
					position: 'absolute',
					top: 0,
					left: 0,
					right: 0,
					paddingTop: SAFE.top - 30,
					paddingBottom: 26,
					background: 'rgba(24,24,30,0.96)',
					borderBottom: '1px solid rgba(255,255,255,0.07)',
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					zIndex: 2,
				}}
			>
				<div style={{width: 96, height: 96, borderRadius: 999, background: 'linear-gradient(135deg,#8A8F9C,#5A5F6B)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 44, fontWeight: 700, color: '#FFF'}}>
					{initial}
				</div>
				<div style={{color: '#FFF', fontSize: 34, fontWeight: 700, marginTop: 12}}>{p.contactName}</div>
				<div style={{color: '#7CD992', fontSize: 24, fontWeight: 500, marginTop: 2}}>{t(p.lang, 'En ligne', 'Online')}</div>
			</div>

			<div style={{position: 'absolute', top: SAFE.top + 220, left: 44, right: 44, transform: `translateY(${-scroll}px)`}}>
				{p.messages.map((m, i) => {
					const showTyping = m.from === 'them' && frame >= typingAt[i] && frame < bubbleAt[i];
					if (showTyping) return <TypingBubble key={i} frame={frame - typingAt[i]} />;
					if (frame < bubbleAt[i]) return null;
					const s = spring({frame: frame - bubbleAt[i], fps, config: {damping: 13, mass: 0.6}});
					const mine = m.from === 'me';
					return (
						<div key={i} style={{display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start', marginBottom: 18}}>
							<div
								style={{
									maxWidth: BUBBLE_MAX_W,
									padding: '24px 32px',
									borderRadius: 40,
									borderBottomRightRadius: mine ? 12 : 40,
									borderBottomLeftRadius: mine ? 40 : 12,
									background: mine ? p.brand.accent : '#26262E',
									color: '#FFF',
									fontSize: BUBBLE_SIZE,
									lineHeight: 1.28,
									fontWeight: 500,
									transform: `scale(${interpolate(s, [0, 1], [0.6, 1])})`,
									transformOrigin: mine ? '100% 100%' : '0% 100%',
									opacity: s,
									whiteSpace: 'pre-wrap',
								}}
							>
								{m.text}
							</div>
						</div>
					);
				})}
			</div>
			<CtaCard brand={p.brand} lang={p.lang} cta={p.cta} startFrame={ctaStart} dark />
		</AbsoluteFill>
	);
};

const TypingBubble: React.FC<{frame: number}> = ({frame}) => (
	<div style={{display: 'flex', marginBottom: 18}}>
		<div style={{background: '#26262E', borderRadius: 40, borderBottomLeftRadius: 12, padding: '30px 34px', display: 'flex', gap: 12}}>
			{[0, 1, 2].map((d) => (
				<div
					key={d}
					style={{
						width: 18,
						height: 18,
						borderRadius: 99,
						background: '#9A9AA5',
						opacity: 0.4 + 0.6 * Math.max(0, Math.sin((frame - d * 4) / 4)),
						transform: `translateY(${-6 * Math.max(0, Math.sin((frame - d * 4) / 4))}px)`,
					}}
				/>
			))}
		</div>
	</div>
);
