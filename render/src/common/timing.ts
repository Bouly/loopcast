import {FPS} from './types';

/** Frames nécessaires pour « taper » un texte à `cps` caractères/seconde. */
export const typeFrames = (text: string, cps = 40) => Math.max(6, Math.ceil((text.length / cps) * FPS));

/** Temps de lecture d'un texte, borné. */
export const readFrames = (text: string, cps = 17, min = 22, max = 95) =>
	Math.min(max, Math.max(min, Math.ceil((text.length / cps) * FPS)));

/**
 * Estime la hauteur d'un bloc de texte (sans mesurer le DOM) :
 * suffisant pour piloter un défilement automatique.
 */
export const estimateTextHeight = (text: string, fontSize: number, maxWidth: number, lineHeight = 1.3) => {
	const charW = fontSize * 0.53;
	const perLine = Math.max(8, Math.floor(maxWidth / charW));
	const lines = text
		.split('\n')
		.reduce((acc, para) => acc + Math.max(1, Math.ceil(para.length / perLine)), 0);
	return lines * fontSize * lineHeight;
};

/** Lisse une fonction de la frame (moyenne glissante) : fonction pure, donc rendu déterministe. */
export const smooth = (fn: (f: number) => number, frame: number, window = 9) => {
	let sum = 0;
	for (let k = 0; k < window; k++) sum += fn(Math.max(0, frame - k));
	return sum / window;
};
