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

// ---------- Écrans d'app factices (placeholder tant qu'on n'a pas les vraies captures) ----------

export type MockScreen =
	| {kind: 'list'; title: string; items: {label: string; done?: boolean}[]}
	| {kind: 'stat'; title: string; value: string; label: string}
	| {kind: 'chart'; title: string; bars: number[]; labels: string[]};

export const MockScreenView: React.FC<{screen: MockScreen; brand: Brand}> = ({screen, brand}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const appear = (i: number) => spring({frame: frame - 6 - i * 5, fps, config: {damping: 16}});
	return (
		<div style={{fontFamily: FONT, padding: '120px 44px 40px', height: '100%', background: '#F6F6FA', color: '#111'}}>
			<div style={{display: 'flex', alignItems: 'center', gap: 18, marginBottom: 40}}>
				<AppIcon brand={brand} size={62} />
				<div style={{fontSize: 44, fontWeight: 800}}>{screen.title}</div>
			</div>
			{screen.kind === 'list' &&
				screen.items.map((it, i) => (
					<div
						key={i}
						style={{
							opacity: appear(i),
							transform: `translateY(${(1 - appear(i)) * 30}px)`,
							background: '#FFF',
							borderRadius: 28,
							padding: '28px 30px',
							marginBottom: 20,
							display: 'flex',
							alignItems: 'center',
							gap: 22,
							boxShadow: '0 4px 14px rgba(0,0,0,0.05)',
						}}
					>
						<div
							style={{
								width: 50,
								height: 50,
								borderRadius: 16,
								background: it.done ? brand.accent : '#E7E7EF',
								color: ink(brand),
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								fontSize: 30,
								fontWeight: 800,
							}}
						>
							{it.done ? '✓' : ''}
						</div>
						<div style={{fontSize: 34, fontWeight: 600, textDecoration: it.done ? 'line-through' : 'none', color: it.done ? '#8A8A96' : '#111'}}>
							{it.label}
						</div>
					</div>
				))}
			{screen.kind === 'stat' && (
				<div style={{textAlign: 'center', marginTop: 120, transform: `scale(${0.6 + appear(0) * 0.4})`, opacity: appear(0)}}>
					<div style={{fontSize: 210, fontWeight: 900, color: brand.accent, lineHeight: 1}}>{screen.value}</div>
					<div style={{fontSize: 40, fontWeight: 600, color: '#55555F', marginTop: 24}}>{screen.label}</div>
				</div>
			)}
			{screen.kind === 'chart' && (
				<div style={{display: 'flex', alignItems: 'flex-end', gap: 18, height: 560, marginTop: 80, padding: '0 10px'}}>
					{screen.bars.map((b, i) => (
						<div key={i} style={{flex: 1, textAlign: 'center'}}>
							<div
								style={{
									height: 480 * Math.max(0.05, Math.min(1, b)) * appear(i),
									background: i === screen.bars.length - 1 ? brand.accent : withAlpha(brand.accent, 0.35),
									borderRadius: 16,
								}}
							/>
							<div style={{fontSize: 26, color: '#77777F', marginTop: 12, fontWeight: 600}}>{screen.labels[i] ?? ''}</div>
						</div>
					))}
				</div>
			)}
		</div>
	);
};
