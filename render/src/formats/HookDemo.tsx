import React from 'react';
import {AbsoluteFill, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT} from '../common/fonts';
import {BaseProps, SAFE} from '../common/types';
import {CtaCard, MockScreen, MockScreenView, Music, PhoneFrame, ScreenImage, withAlpha} from '../common/ui';

/**
 * Format « hook + démo » : une accroche plein écran (mots qui tombent un par un),
 * puis 2 à 5 écrans de l'app dans un téléphone, chacun avec sa légende, puis CTA.
 * Dans le hook, entourer un mot de **…** le colore avec l'accent de la marque.
 * Un écran est une vraie capture (`src`, chemin dans public/) ou, à défaut, un écran factice (`mock`).
 */
export type DemoScreen = {caption: string; src?: string; mock?: MockScreen};
export type HookDemoProps = BaseProps & {
	hook: string;
	screens: DemoScreen[];
};

const WORD_STEP = 5;
const SCREEN_LEN = 78;
const CTA_HOLD = 85;
const PHONE_W = 600; // assez grand pour que l'écran reste lisible sur un iPhone
const PHONE_TOP = 400;

const words = (hook: string) => hook.split(/\s+/).filter(Boolean);

export const hookDemoTimeline = (p: HookDemoProps) => {
	const hookLen = Math.max(84, words(p.hook).length * WORD_STEP + 50);
	const screensStart = hookLen;
	const ctaStart = screensStart + p.screens.length * SCREEN_LEN;
	return {hookLen, screensStart, ctaStart, total: ctaStart + CTA_HOLD};
};

export const HookDemo: React.FC<HookDemoProps> = (p) => {
	const {hookLen, screensStart, ctaStart} = hookDemoTimeline(p);
	return (
		<AbsoluteFill style={{fontFamily: FONT, background: '#0E0E12'}}>
			<Music src={p.music} />
			<Sequence durationInFrames={hookLen + 8}>
				<Hook {...p} len={hookLen} />
			</Sequence>
			<Sequence from={screensStart}>
				<ScreensBg accent={p.brand.accent} />
			</Sequence>
			{p.screens.map((s, i) => (
				<Sequence key={i} from={screensStart + i * SCREEN_LEN} durationInFrames={i === p.screens.length - 1 ? undefined : SCREEN_LEN + 10}>
					<ScreenSlide screen={s} p={p} last={i === p.screens.length - 1} />
				</Sequence>
			))}
			<CtaCard brand={p.brand} lang={p.lang} cta={p.cta} startFrame={ctaStart} />
		</AbsoluteFill>
	);
};

const Hook: React.FC<HookDemoProps & {len: number}> = (p) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const list = words(p.hook);
	const exit = interpolate(frame, [p.len - 6, p.len + 6], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const zoom = interpolate(frame, [0, p.len], [1, 1.06]);
	return (
		<AbsoluteFill
			style={{
				background: `radial-gradient(circle at 50% 35%, ${withAlpha(p.brand.accent, 0.35)}, #0E0E12 70%)`,
				justifyContent: 'center',
				padding: `0 ${SAFE.right}px 0 ${SAFE.left + 10}px`,
				opacity: exit,
			}}
		>
			<div style={{transform: `scale(${zoom})`, display: 'flex', flexWrap: 'wrap', gap: '6px 22px', marginTop: -160}}>
				{list.map((w, i) => {
					const s = spring({frame: frame - i * WORD_STEP, fps, config: {damping: 12, mass: 0.5}});
					const accent = w.startsWith('**') || w.endsWith('**');
					return (
						<span
							key={i}
							style={{
								fontSize: 104,
								fontWeight: 900,
								lineHeight: 1.08,
								letterSpacing: -2,
								color: accent ? p.brand.accent : '#FFFFFF',
								opacity: s,
								transform: `translateY(${(1 - s) * 60}px) scale(${0.85 + s * 0.15})`,
								display: 'inline-block',
								textShadow: '0 6px 30px rgba(0,0,0,0.35)',
							}}
						>
							{w.replace(/\*\*/g, '')}
						</span>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};

const ScreensBg: React.FC<{accent: string}> = ({accent}) => (
	<AbsoluteFill style={{background: `linear-gradient(180deg, ${withAlpha(accent, 0.18)} 0%, #F4F4F8 55%)`}} />
);

const ScreenSlide: React.FC<{screen: DemoScreen; p: HookDemoProps; last: boolean}> = ({screen, p, last}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const enter = spring({frame, fps, config: {damping: 15, mass: 0.7}});
	const exitP = last ? 0 : interpolate(frame, [SCREEN_LEN - 4, SCREEN_LEN + 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const x = interpolate(enter, [0, 1], [900, 0]) - exitP * 900;
	const captionIn = spring({frame: frame - 4, fps, config: {damping: 14}});
	const zoom = interpolate(frame, [0, SCREEN_LEN], [1, 1.03]); // léger mouvement pendant la lecture
	return (
		<AbsoluteFill>
			<div
				style={{
					position: 'absolute',
					top: SAFE.top + 10,
					left: SAFE.left,
					right: SAFE.right - 40,
					fontSize: 62,
					fontWeight: 800,
					color: '#121216',
					lineHeight: 1.12,
					letterSpacing: -1,
					opacity: captionIn * (1 - exitP),
					transform: `translateY(${(1 - captionIn) * -30}px)`,
				}}
			>
				{screen.caption}
			</div>
			<div
				style={{
					position: 'absolute',
					top: PHONE_TOP,
					left: 0,
					right: 0,
					display: 'flex',
					justifyContent: 'center',
					transform: `translateX(${x}px) rotate(${(1 - enter) * 6}deg) scale(${zoom})`,
					transformOrigin: '50% 30%',
				}}
			>
				<PhoneFrame width={PHONE_W}>
					{screen.src ? <ScreenImage src={screen.src} /> : screen.mock ? <MockScreenView screen={screen.mock} brand={p.brand} width={PHONE_W} /> : null}
				</PhoneFrame>
			</div>
		</AbsoluteFill>
	);
};
