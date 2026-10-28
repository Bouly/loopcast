import React from 'react';
import {AbsoluteFill, Audio, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT} from './fonts';
import {Brand, Lang, SAFE, t} from './types';

export const ink = (brand: Brand) => brand.accentInk ?? '#FFFFFF';

export const withAlpha = (hex: string, alpha: number) => {
	const h = hex.replace('#', '');
	const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
	return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};

export const AppIcon: React.FC<{brand: Brand; size: number}> = ({brand, size}) => (
	<div
		style={{
			width: size,
			height: size,
			borderRadius: size * 0.23,
			background: brand.accent,
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			overflow: 'hidden',
			boxShadow: `0 ${size * 0.08}px ${size * 0.25}px ${withAlpha(brand.accent, 0.35)}`,
			flexShrink: 0,
		}}
	>
		{brand.icon ? (
			<Img src={staticFile(brand.icon)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
		) : (
			<span style={{fontFamily: FONT, fontWeight: 800, fontSize: size * 0.5, color: ink(brand)}}>
				{brand.name.charAt(0).toUpperCase()}
			</span>
		)}
	</div>
);

/** Carte d'appel à l'action qui monte depuis le bas, au-dessus de la zone masquée par TikTok. */
export const CtaCard: React.FC<{brand: Brand; lang: Lang; cta: string; startFrame: number; dark?: boolean}> = ({
	brand,
	lang,
	cta,
	startFrame,
	dark = false,
}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	if (frame < startFrame) return null;
	const p = spring({frame: frame - startFrame, fps, config: {damping: 14, mass: 0.8}});
	const storeLine = brand.storeLine ?? t(lang, "Gratuit sur l'App Store et Google Play", 'Free on the App Store & Google Play');
	return (
		<AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: SAFE.bottom - 40}}>
			<div
				style={{
					transform: `translateY(${interpolate(p, [0, 1], [500, 0])}px) scale(${interpolate(p, [0, 1], [0.9, 1])})`,
					width: 1080 - SAFE.left * 2,
					background: dark ? '#17171C' : '#FFFFFF',
					borderRadius: 44,
					padding: '36px 40px',
					display: 'flex',
					alignItems: 'center',
					gap: 32,
					boxShadow: '0 30px 80px rgba(0,0,0,0.28)',
					border: dark ? '1px solid rgba(255,255,255,0.08)' : 'none',
				}}
			>
				<AppIcon brand={brand} size={130} />
				<div style={{flex: 1, fontFamily: FONT}}>
					<div style={{fontSize: 46, fontWeight: 800, color: dark ? '#FFF' : '#111', lineHeight: 1.1}}>{cta}</div>
					<div style={{fontSize: 30, fontWeight: 500, color: dark ? '#A8A8B3' : '#6B6B76', marginTop: 10}}>
						{brand.name} · {storeLine}
					</div>
				</div>
			</div>
		</AbsoluteFill>
	);
};

export const Music: React.FC<{src?: string}> = ({src}) => (src ? <Audio src={staticFile(src)} volume={0.6} /> : null);

/** Cadre de téléphone générique (aucune marque), pour les captures d'app. */
export const PhoneFrame: React.FC<{width: number; children: React.ReactNode}> = ({width, children}) => {
	const height = width * 2.05;
	return (
		<div
			style={{
				width,
				height,
				borderRadius: width * 0.13,
				background: '#0B0B0F',
				padding: width * 0.035,
				boxShadow: '0 50px 120px rgba(0,0,0,0.45)',
				position: 'relative',
			}}
		>
			<div style={{width: '100%', height: '100%', borderRadius: width * 0.1, overflow: 'hidden', background: '#FFF', position: 'relative'}}>
				{children}
			</div>
			<div
				style={{
					position: 'absolute',
					top: width * 0.06,
					left: '50%',
					transform: 'translateX(-50%)',
					width: width * 0.28,
					height: width * 0.075,
					borderRadius: 999,
					background: '#0B0B0F',
				}}
			/>
		</div>
	);
};

/** Une vraie capture d'écran dans le téléphone : on garde le haut (barre d'état, titre), on rogne le bas. */
export const ScreenImage: React.FC<{src: string}> = ({src}) => (
	<Img
		src={src.startsWith('http') ? src : staticFile(src)}
		style={{width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top'}}
	/>
);

// ---------- Écrans d'app factices (placeholder tant qu'on n'a pas les vraies captures) ----------

export type MockScreen =
	| {kind: 'list'; title: string; items: {label: string; done?: boolean}[]}
	| {kind: 'stat'; title: string; value: string; label: string}
	| {kind: 'chart'; title: string; bars: number[]; labels: string[]};

/**
 * Écran factice dessiné pour un `PhoneFrame` de largeur `width`. Les tailles suivent la largeur du
 * téléphone et restent lisibles une fois la vidéo affichée sur un iPhone (texte ≥ 44 px pour 600 px).
 */
export const MockScreenView: React.FC<{screen: MockScreen; brand: Brand; width?: number}> = ({screen, brand, width = 600}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const k = width / 600;
	const appear = (i: number) => spring({frame: frame - 6 - i * 5, fps, config: {damping: 16}});
	return (
		<div style={{fontFamily: FONT, padding: `${132 * k}px ${30 * k}px ${40 * k}px`, height: '100%', background: '#F6F6FA', color: '#111'}}>
			<div style={{display: 'flex', alignItems: 'center', gap: 18 * k, marginBottom: 34 * k, paddingLeft: 6 * k}}>
				<AppIcon brand={brand} size={68 * k} />
				<div style={{fontSize: 54 * k, fontWeight: 800, letterSpacing: -0.5}}>{screen.title}</div>
			</div>
			{screen.kind === 'list' &&
				screen.items.map((it, i) => (
					<div
						key={i}
						style={{
							opacity: appear(i),
							transform: `translateY(${(1 - appear(i)) * 30 * k}px)`,
							background: '#FFF',
							borderRadius: 30 * k,
							padding: `${26 * k}px ${26 * k}px`,
							marginBottom: 18 * k,
							display: 'flex',
							alignItems: 'center',
							gap: 22 * k,
							boxShadow: '0 4px 14px rgba(0,0,0,0.06)',
						}}
					>
						<div
							style={{
								width: 60 * k,
								height: 60 * k,
								borderRadius: 18 * k,
								background: it.done ? brand.accent : '#E3E3EC',
								color: ink(brand),
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								fontSize: 38 * k,
								fontWeight: 800,
								flexShrink: 0,
							}}
						>
							{it.done ? '✓' : ''}
						</div>
						<div style={{fontSize: 44 * k, fontWeight: 600, lineHeight: 1.15, textDecoration: it.done ? 'line-through' : 'none', color: it.done ? '#8A8A96' : '#111'}}>
							{it.label}
						</div>
					</div>
				))}
			{screen.kind === 'stat' && (
				<div style={{textAlign: 'center', marginTop: 130 * k, transform: `scale(${0.6 + appear(0) * 0.4})`, opacity: appear(0)}}>
					<div style={{fontSize: 250 * k, fontWeight: 900, color: brand.accent, lineHeight: 1, letterSpacing: -6 * k}}>{screen.value}</div>
					<div style={{fontSize: 50 * k, fontWeight: 700, color: '#4A4A55', marginTop: 26 * k}}>{screen.label}</div>
				</div>
			)}
			{screen.kind === 'chart' && (
				<div style={{display: 'flex', alignItems: 'flex-end', gap: 16 * k, height: 640 * k, marginTop: 80 * k, padding: `0 ${8 * k}px`}}>
					{screen.bars.map((b, i) => (
						<div key={i} style={{flex: 1, textAlign: 'center'}}>
							<div
								style={{
									height: 560 * k * Math.max(0.05, Math.min(1, b)) * appear(i),
									background: i === screen.bars.length - 1 ? brand.accent : withAlpha(brand.accent, 0.35),
									borderRadius: 16 * k,
								}}
							/>
							<div style={{fontSize: 38 * k, color: '#5F5F6A', marginTop: 14 * k, fontWeight: 700}}>{screen.labels[i] ?? ''}</div>
						</div>
					))}
				</div>
			)}
		</div>
	);
};
