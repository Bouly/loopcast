#!/usr/bin/env node
/**
 * Rendu par lot : node render.mjs <manifest.json>
 *
 * manifest = { "jobs": [
 *   { "id": "...", "composition": "notes-app", "props": {...}, "out": "/abs/out.mp4" },
 *   { "id": "...", "composition": "slideshow", "props": {...}, "outDir": "/abs/dir", "stills": 4 }
 * ]}
 *
 * Écrit une ligne JSON par job sur stdout : {"id","ok","files"|"error"}.
 * Variable REMOTION_BROWSER : chemin d'un Chrome headless déjà installé (sinon Remotion télécharge le sien).
 */
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const manifestPath = process.argv[2];
if (!manifestPath) {
	console.error('Usage: node render.mjs <manifest.json>');
	process.exit(2);
}
const {jobs} = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const browserExecutable = process.env.REMOTION_BROWSER || null;
const log = (...a) => console.error('[render]', ...a);

log(`bundle… (${jobs.length} job(s))`);
const serveUrl = await bundle({
	entryPoint: path.join(here, 'src/index.ts'),
	publicDir: path.join(here, 'public'),
});

for (const job of jobs) {
	const started = Date.now();
	try {
		const files = [];
		if (job.stills) {
			fs.mkdirSync(job.outDir, {recursive: true});
			for (let i = 0; i < job.stills; i++) {
				const inputProps = {...job.props, slideIndex: i};
				const composition = await selectComposition({serveUrl, id: job.composition, inputProps, browserExecutable});
				const output = path.join(job.outDir, `${String(i + 1).padStart(2, '0')}.png`);
				await renderStill({composition, serveUrl, output, inputProps, browserExecutable});
				files.push(output);
			}
		} else {
			fs.mkdirSync(path.dirname(job.out), {recursive: true});
			const composition = await selectComposition({serveUrl, id: job.composition, inputProps: job.props, browserExecutable});
			let lastBucket = -1;
			await renderMedia({
				composition,
				serveUrl,
				codec: 'h264',
				crf: 20,
				x264Preset: 'veryfast',
				pixelFormat: 'yuv420p',
				outputLocation: job.out,
				inputProps: job.props,
				browserExecutable,
				onProgress: ({progress}) => {
					const bucket = Math.floor(progress * 4);
					if (bucket !== lastBucket) {
						lastBucket = bucket;
						log(`${job.id} ${bucket * 25}%`);
					}
				},
			});
			files.push(job.out);
		}
		log(`${job.id} ok en ${((Date.now() - started) / 1000).toFixed(1)}s`);
		process.stdout.write(JSON.stringify({id: job.id, ok: true, files}) + '\n');
	} catch (err) {
		log(`${job.id} ÉCHEC`, err?.message ?? err);
		process.stdout.write(JSON.stringify({id: job.id, ok: false, error: String(err?.message ?? err)}) + '\n');
	}
}
