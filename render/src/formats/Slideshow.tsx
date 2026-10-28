import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {FONT} from '../common/fonts';
import {BaseProps, SAFE, t} from '../common/types';
import {AppIcon, withAlpha} from '../common/ui';

/**
 * Format « slideshow » (mode photo TikTok / carrousel Instagram) : rendu en images fixes.
 * La slide 0 est le hook, les suivantes le contenu ; une slide CTA est ajoutée à la fin.
 * `bg` peut pointer vers une image (plus tard : générée par IA) dans public/.
 */
export type Slide = {title: string; body?: string; emoji?: string; bg?: string};
export type SlideshowProps = BaseProps & {
	slides: Slide[];
	slideIndex: number;
};

export const slideCount = (p: Pick<SlideshowProps, 'slides'>) => p.slides.length + 1;

export const Slideshow: React.FC<SlideshowProps> = (p) => {
	const isCta = p.slideIndex >= p.slides.length;
	const slide = p.slides[Math.min(p.slideIndex, p.slides.length - 1)];
	const isHook = p.slideIndex === 0;
	const bg = !isCta && slide.bg ? staticFile(slide.bg) : undefined;
	return (
		<AbsoluteFill
			style={{
				fontFamily: FONT,
				background: `linear-gradient(160deg, ${withAlpha(p.brand.accent, 0.95)} 0%, #121218 75%)`,
			}}
		>
			{bg && (
				<>
					<Img src={bg} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} />
					<AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(0,0,0,0.15), rgba(0,0,0,0.65))'}} />
				</>
			)}
			{isCta ? (
				<CtaSlide {...p} />
			) : (
				<AbsoluteFill style={{justifyContent: 'center', padding: `${SAFE.top}px ${SAFE.right}px ${SAFE.bottom}px ${SAFE.left + 6}px`}}>
					{slide.emoji && <div style={{fontSize: isHook ? 150 : 120, marginBottom: 40}}>{slide.emoji}</div>}
					{isHook ? (
						<div style={{display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 14}}>
							{slide.title.split('\n').map((line, i) => (
								<span
									key={i}
									style={{
										background: '#FFFFFF',
										color: '#111',
										fontSize: 86,
										fontWeight: 900,
										lineHeight: 1.12,
										padding: '10px 26px',
										borderRadius: 22,
										letterSpacing: -1.5,
									}}
								>
									{line}
								</span>
							))}
						</div>
					) : (
						<>
							<div style={{fontSize: 34, fontWeight: 800, color: withAlpha('#FFFFFF', 0.6), marginBottom: 22}}>
								{p.slideIndex}/{p.slides.length - 1}
							</div>
							<div style={{fontSize: 82, fontWeight: 900, color: '#FFF', lineHeight: 1.1, letterSpacing: -1.5, textShadow: '0 4px 24px rgba(0,0,0,0.3)'}}>
								{slide.title}
							</div>
						</>
					)}
					{slide.body && (
						<div style={{fontSize: 46, fontWeight: 500, color: 'rgba(255,255,255,0.88)', lineHeight: 1.35, marginTop: 36}}>{slide.body}</div>
					)}
				</AbsoluteFill>
			)}
		</AbsoluteFill>
	);
};

const CtaSlide: React.FC<SlideshowProps> = (p) => (
	<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: `${SAFE.top}px ${SAFE.right}px ${SAFE.bottom}px ${SAFE.left}px`, textAlign: 'center'}}>
		<AppIcon brand={p.brand} size={260} />
		<div style={{fontSize: 92, fontWeight: 900, color: '#FFF', marginTop: 56, letterSpacing: -2}}>{p.brand.name}</div>
		<div style={{fontSize: 56, fontWeight: 700, color: '#FFF', marginTop: 28, lineHeight: 1.2}}>{p.cta}</div>
		<div style={{fontSize: 36, fontWeight: 500, color: 'rgba(255,255,255,0.75)', marginTop: 26}}>
			{p.brand.storeLine ?? t(p.lang, "Gratuit sur l'App Store et Google Play", 'Free on the App Store & Google Play')}
		</div>
	</AbsoluteFill>
);
