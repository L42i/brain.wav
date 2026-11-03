// =====================================================================
// FluCoMa vocal drone
// Database: <root>/<singer 1-6>/<vowel a e i o u>/<low|mid|high>/<breathy|raspy|supported>.wav
// 270 files. Each file is cut into short segments, each segment becomes one
// point in a 3D descriptor space:
//     [ pitch (MIDI), spectral centroid (MIDI), spectral flatness (dB) ]
// Three normalized controls (0..1) query a KD-tree on the server; the k nearest
// segments are granulated and (optionally) transposed to a common drone note.
//
//     x  -> brightness  (centroid, largely vowel: u/o dark ... i/e bright)
//     y  -> noisiness   (flatness, largely voice quality: supported ... breathy/raspy)
//     z  -> register    (pitch: low ... high)
// =====================================================================


// SET THE PATH TO THE SAMPLES FIRST.
// this works on LINUX only:
(
~tmp = PathName(thisProcess.nowExecutingPath).parentPath;
~sample_dir = ~tmp++"../samples";   // <-- folder that contains 1 ... 6
)



// ---------------------------------------------------------------------
// 0. Boot
// ---------------------------------------------------------------------
(

 s.options.numBuffers = 2048;
 s.options.memSize = 2 ** 16;
 s.boot;

)


// ---------------------------------------------------------------------
// 1. Collect files (folder names = metadata)
// ---------------------------------------------------------------------
(


~files = List[];
PathName(~sample_dir).folders.do { |singer|
	singer.folders.do { |vowel|
		vowel.folders.do { |reg|
			// reg.files ignores the (empty) 'peaks' subfolders
			reg.files.select { |f| f.extension.toLower == "wav" }.do { |f|
				~files.add((
					path:   f.fullPath,
					singer: singer.folderName,
					vowel:  vowel.folderName,
					reg:    reg.folderName,
					qual:   f.fileNameWithoutExtension.toLower  // 1/a/low has "Raspy"/"Supported"
				));
			}
		}
	}
};
"% files found (expected 270)".format(~files.size).postln;
)


// ---------------------------------------------------------------------
// 2. Load, analyse, segment, build datasets + KD-tree
// ---------------------------------------------------------------------
(
~segDur  = 0.25;   // segment length (s)
~segHop  = 0.125;  // segment hop (s)
~trim    = 0.15;   // skip first/last 15 % of each file (onset, release)
~minConf = 0.5;    // pitch confidence threshold
~hop     = 512;    // analysis hop (samples)
~k       = 4;      // number of neighbours (defined here, outside the async fork)

// fail loudly instead of silently hanging
if(s.serverRunning.not) { Error("Server not running - evaluate step 0 first").throw };
if(~files.isNil or: { ~files.isEmpty }) { Error("No files - check ~sample_dir and re-run step 1").throw };
"step 2: starting with % files".format(~files.size).postln;

fork {
	var shapeBuf = Buffer(s), pitchBuf = Buffer(s);
	var cond = Condition.new;
	var points = Dictionary.new, lookup = Dictionary.new;
	// race-safe wait for async language-side callbacks
	var fetch = { |b| var out; cond.test = false;
		b.loadToFloatArray(action: { |a| out = a; cond.test = true; cond.signal });
		cond.wait; out };

	"loading buffers ...".postln;
	// load in small batches: firing 270 async reads at once over UDP can drop
	// messages (incl. the /sync reply) and leave the routine waiting forever
	~bufs = ~files.collect { |f, i|
		var b = Buffer.readChannel(s, f.path, channels: [0]);
		if(i % 10 == 9) { s.sync; "  % / % loaded".format(i + 1, ~files.size).postln };
		b
	};
	s.sync;
	"% buffers loaded, first: % frames @ % Hz".format(
		~bufs.size, ~bufs[0].numFrames, ~bufs[0].sampleRate).postln;

	~bufs.do { |buf, fi|
		var f = ~files[fi], sh, pc, nFr, segLen, segHop, start, stop;
		var verbose = fi < 2;   // detailed posts for the first files only

		if(verbose) { "file %: spectral shape".format(fi).postln };
		FluidBufSpectralShape.processBlocking(s, buf, features: shapeBuf,
			select: [\centroid, \flatness], unit: 1,       // centroid in MIDI
			windowSize: 2048, hopSize: ~hop);
		s.sync;
		if(verbose) { "file %: pitch".format(fi).postln };
		FluidBufPitch.processBlocking(s, buf, features: pitchBuf,
			select: [\pitch, \confidence], unit: 1,        // pitch in MIDI
			windowSize: 2048, hopSize: ~hop);
		s.sync;

		if(verbose) { "file %: fetching features".format(fi).postln };
		sh = fetch.(shapeBuf).clump(2);
		pc = fetch.(pitchBuf).clump(2);
		if(verbose) { "file %: % shape frames, % pitch frames".format(fi, sh.size, pc.size).postln };

		nFr    = min(sh.size, pc.size);
		segLen = (~segDur * buf.sampleRate / ~hop).round.asInteger;
		segHop = (~segHop * buf.sampleRate / ~hop).round.asInteger.max(1);
		start  = (nFr * ~trim).asInteger;
		stop   = (nFr * (1 - ~trim)).asInteger - segLen;

		forBy(start, stop, segHop) { |i|
			var shs  = sh[i .. i + segLen - 1];
			var good = pc[i .. i + segLen - 1].select { |p| p[1] > ~minConf };
			if(good.size > (segLen / 2)) {
				var id = "%-%-%-%-%".format(f.singer, f.vowel, f.reg, f.qual, i);
				var p  = good.collect(_[0]).median;
				points[id] = [p, shs.collect(_[0]).median, shs.collect(_[1]).median];
				// what the synth needs back: which buffer, where (samples), its pitch
				lookup[id] = [buf.bufnum, (i + (segLen / 2)) * ~hop, p];
			};
		};
		if(fi % 20 == 0) { "analysed % / %".format(fi, ~bufs.size).postln };
	};

	~ds       = FluidDataSet(s);
	~dsNorm   = FluidDataSet(s);
	~lookupDS = FluidDataSet(s);
	~ds.load(Dictionary["cols" -> 3, "data" -> points]);
	~lookupDS.load(Dictionary["cols" -> 3, "data" -> lookup]);
	s.sync;

	~norm = FluidNormalize(s);            // try FluidRobustScale if outliers squash the range
	~norm.fitTransform(~ds, ~dsNorm);
	s.sync;

	~tree = FluidKDTree(s, numNeighbours: ~k);
	~tree.fit(~dsNorm);
	s.sync;

	"done: % segments".format(points.size).postln;
	~dsNorm.print;
};
)

// optional: save so you can skip step 2 next time (buffers still need loading)
// ~ds.write("~/drone_ds.json".standardizePath); ~lookupDS.write("~/drone_lookup.json".standardizePath);


// ---------------------------------------------------------------------
// 3. Synth
// ---------------------------------------------------------------------
(
if(~tree.isNil or: { ~lookupDS.isNil }) {
	Error("Analysis not finished (or failed) - wait for 'done: N segments' from step 2").throw;
};
SynthDef(\fluidDrone, { |out = 0, amp = 0.4,
	x = 0.5, y = 0.2, z = 0.5,            // brightness, noisiness, register (0..1)
	note = 50, lock = 1,                  // lock=1: transpose all grains to 'note'
	density = 14, grainDur = 0.45, jitter = 0.08, detune = 0.08|

	var inBuf  = LocalBuf(3);
	var outBuf = LocalBuf(~k * 3);
	var nn, sig;

	// query order must match dataset columns: [pitch, centroid, flatness]
	FluidKrToBuf.kr([z, x, y].lag(0.3), inBuf);
	// keyword args: positional order of .kr differs between FluCoMa versions
	~tree.kr(Impulse.kr(20), inBuf, outBuf, numNeighbours: ~k, lookupDataSet: ~lookupDS);
	nn = FluidBufToKr.kr(outBuf, numFrames: ~k * 3).clump(3);   // [[bufnum, pos, pitch] ...]

	sig = nn.collect { |v, j|
		var buf = v[0], pos = v[1], p = v[2];
		var trig = Dust.kr(density / ~k * 2);
		var rate = ((note - p) * lock).midiratio
		         * LFNoise1.kr(0.2).range(detune.neg, detune).midiratio;
		var centre = (pos / BufSampleRate.kr(buf)) + TRand.kr(jitter.neg, jitter, trig);
		TGrains.ar(2, trig, buf, rate, centre, grainDur,
			TRand.kr(-0.8, 0.8, trig), 1 / (j + 1), 4);   // nearer neighbours louder
	}.sum;

	sig = LeakDC.ar(sig) * amp;
	Out.ar(out, Limiter.ar(sig, 0.9));
}).add;
)


// ---------------------------------------------------------------------
// 4. Play + simple controller
// ---------------------------------------------------------------------
(
~drone = Synth(\fluidDrone);

w = Window("fluid drone", Rect(100, 100, 360, 320)).front;
StaticText(w, Rect(10, 290, 280, 20)).string_("x: brightness    y: noisiness");
StaticText(w, Rect(300, 290, 60, 20)).string_("register");
Slider2D(w, Rect(10, 10, 280, 280)).x_(0.5).y_(0.2)
	.action_({ |v| ~drone.set(\x, v.x, \y, v.y) });
Slider(w, Rect(305, 10, 40, 280)).value_(0.5)
	.action_({ |v| ~drone.set(\z, v.value) });
w.onClose = { ~drone.free };
)

// other knobs
~drone.set(\note, 122);          // drone fundamental
~drone.set(\lock, 1);           // 0 = keep the singers' own pitches (more chorus / beating)
~drone.set(\grainDur, 0.2, \density, 100);





(
var win = Window("drone params", Rect(480, 100, 420, 190)).front;
win.addFlowLayout(10@10, 5@8);

EZSlider(win, 400@24, "note", ControlSpec(24, 127, \lin, 0.1, 50),
	{ |ez| ~drone.set(\note, ez.value) }, labelWidth: 70, numberWidth: 50);

EZSlider(win, 400@24, "grainDur", ControlSpec(0.02, 2, \exp, 0, 0.45, "s"),
	{ |ez| ~drone.set(\grainDur, ez.value) }, labelWidth: 70, numberWidth: 50);

EZSlider(win, 400@24, "density", ControlSpec(1, 200, \exp, 0, 14, "Hz"),
	{ |ez| ~drone.set(\density, ez.value) }, labelWidth: 70, numberWidth: 50);

EZSlider(win, 400@24, "detune", ControlSpec(0, 1, \lin, 0, 0.08, "st"),
	{ |ez| ~drone.set(\detune, ez.value) }, labelWidth: 70, numberWidth: 50);

EZSlider(win, 400@24, "amp", ControlSpec(0, 1, \amp, 0, 0.4),
	{ |ez| ~drone.set(\amp, ez.value) }, labelWidth: 70, numberWidth: 50);

Button(win, 195@24)
	.states_([["lock: OFF (own pitches)"], ["lock: ON (to note)", Color.black, Color.green(0.8)]])
	.value_(1)
	.action_({ |b| ~drone.set(\lock, b.value) });
)