function OCRExtractor(varargin)
% STEP2_OCREXTRACTOR
%  - GUI-Modus:   step2_OCRExtractor()
%  - CLI-Modus:   step2_OCRExtractor(filePath)
%                 step2_OCRExtractor(filePath, true)
%                 step2_OCRExtractor(filePath, 'runocr')

% clearvars;

%% Globale Flags
nFramesOcrProgress = 2;         % Live Update bei OCR; alle n Frames

% unten: normalerweise false
ANALYZE_RPM_ON_START = false;   % Bei Startup RPM-Spektrogrammanalyse durchführen  
analyzeRPMAfterOCR = false;     % nach OCR direkt RPM-Spektrogrammanalyse

% unten: normalerweise true
DEBUG = true;                   % Zeige Logs
ocrResumeIfPossible = true;    % wenn OCR schon mal abgebrochen wurde, fortsetzen, wenn möglich
noTrackCalibIfPoss = true;     % Karte nicht erneut kalibrieren (bei ROI: track_minimap), wenn möglich
overwriteIfPossible = true;    % überschreibe .mat-Datei, wenn möglich

%% ------------------------------------------------------------------------
% CLI-Parameter auswerten
% -------------------------------------------------------------------------
cliFilePath  = "";
cliRunOCR    = false;

if nargin == 0
    clc;
    close all;
else
    overwriteIfPossible = true;
end

if nargin >= 1 && ~isempty(varargin{1})
    cliFilePath = string(varargin{1});
end

if nargin >= 2 && ~isempty(varargin{2})
    flag = varargin{2};
    if islogical(flag)
        cliRunOCR = flag;
    elseif ischar(flag) || isstring(flag)
        cliRunOCR = any(strcmpi(string(flag), ["runocr","ocr","run_ocr"]));
    end
end

%% ===== Debug-Auswahl & Logger =====
% choice = questdlg('Debug-Modus aktivieren?','Debug','Ja','Nein','Ja');
% DEBUG = strcmp(choice,'Ja');
if DEBUG
    LOG = @(varargin) fprintf('[%s] %s\n', ...
        string(datetime("now"), 'HH:mm:ss.SSS'), sprintf(varargin{:}));
else
    LOG = @(varargin) [];   % No-op
end
LOG('Script gestartet.');

%% Datei wählen / oder über CLI bekommen
if cliFilePath == ""
    % --- Klassischer GUI-Modus: Datei wählen ---
    [file, location] = uigetfile("MultiSelect","off", fullfile("results", "results_*.mat"));
    if isequal(file,0) || isequal(location,0)
        disp("Datei nicht gewählt. Skript abgebrochen.")
        return
    end
    filePath = fullfile(location, file);
else
    % --- CLI-Modus: filePath kam als Argument ---
    filePath = char(cliFilePath);
    if ~isfile(filePath)
        error('step2_OCRExtractor:FileNotFound', ...
            'MAT-Datei nicht gefunden: %s', filePath);
    end
end

LOG('Gewählte Datei: %s', filePath);

% lade recordResult
S = load(filePath);  % erwartet: enthält recordResult
if ~isfield(S, 'recordResult')
    error('In %s wurde kein "recordResult" gefunden.', filePath);
end
recordResult = S.recordResult;

save(filePath, 'recordResult', '-v7.3');  % sofort persistieren


% ==== Legacy-Aufräumen: Pfade gehören nach recordResult.metadata ====
if isfield(recordResult,'ocr') && isstruct(recordResult.ocr)
    % Alte Felder entfernen, falls vorhanden
    if isfield(recordResult.ocr,'video')
        recordResult.ocr = rmfield(recordResult.ocr,'video');
    end
    if isfield(recordResult.ocr,'audio')
        recordResult.ocr = rmfield(recordResult.ocr,'audio');
    end
end

% --- Prüfen, ob bereits ein OCR-Ergebnis existiert und ggf. nachfragen
% ocrExists = isfield(recordResult,'ocr') && ...
            % isfield(recordResult.ocr,'table') && ~isempty(recordResult.ocr.table);
ocrExists = isfield(recordResult,'ocr');
overwriteAllowed = true;
if ocrExists
    if overwriteIfPossible
        choiceOverwrite = 'Überschreiben';
    else
        choiceOverwrite = questdlg( ...
            ['In dieser MAT-Datei existiert bereits ein OCR-Ergebnis.' newline ...
             'Soll es überschrieben werden?'], ...
            'OCR-Ergebnis vorhanden', ...
            'Überschreiben','Behalten','Überschreiben');
    end
    
    overwriteAllowed = strcmp(choiceOverwrite,'Überschreiben');
end

% --- Falls Überschreiben: vorhandene OCR-Parameter zum Vorbelegen sichern
preParams = struct();
if ocrExists && overwriteAllowed
    if isfield(recordResult,'ocr')
        try
            po = recordResult.ocr;
            if isfield(po,'params')
                pp = po.params;
                if isfield(pp,'start_s'),        preParams.start_s  = double(pp.start_s);        end
                if isfield(pp,'end_s'),          preParams.end_s    = double(pp.end_s);          end
                if isfield(pp,'audio_offset_s'), preParams.offset_s = double(pp.audio_offset_s); end
            end
            if isfield(po,'roi_table')
                preParams.roi_table = po.roi_table; 
            end
            if isfield(po, 'track')
                pTrack = po.track;
                if isfield(pTrack,'trackName'),         preParams.track   = string(pTrack.trackName);   end
            end
            if isfield(po,'cleaned_info')
                pClea = po.cleaned_info;
                if isfield(pClea,'track'),              preParams.track   = string(pClea.track);        end
            end
            if isfield(po,'processed_info')
                pInfo = po.processed_info;
                if isfield(pInfo,'acc_min_mps2'),       preParams.acc_min = double(pInfo.acc_min_mps2); end
                if isfield(pInfo,'acc_max_mps2'),       preParams.acc_max = double(pInfo.acc_max_mps2); end
                if isfield(pInfo,'v_min_kmph'),         preParams.v_min   = double(pInfo.v_min_kmph);   end
                if isfield(pInfo,'v_max_kmph'),         preParams.v_max   = double(pInfo.v_max_kmph);   end
                if isfield(pInfo,'track'),              preParams.track   = string(pInfo.track);        end % overwrite cleaned_info
                if isfield(pInfo,'apply_track_correction')
                    preParams.apply_corr = logical(pInfo.apply_track_correction);
                end
            end
        catch
        end
    end

    if isfield(recordResult,'audio_rpm')
        try
            audio = recordResult.audio_rpm;
            if isfield(po, 'params')
                audioParams = audio.params;
                if isfield(audioParams, 'use_v'),       preParams.use_v = audioParams.use_v; end
                if isfield(audioParams, 'tol_pct'),     preParams.tol_pct = audioParams.tol_pct; end
                if isfield(audioParams, 'tol_abs'),     preParams.tol_abs = audioParams.tol_abs; end
                if isfield(audioParams, 'i_axle'),      preParams.i_axle = audioParams.i_axle; end
                if isfield(audioParams, 'gears'),       preParams.gears = audioParams.gears; end
                if isfield(audioParams, 'r_dyn'),       preParams.r_dyn = audioParams.r_dyn; end
                if isfield(audioParams, 'prefer_low'),  preParams.prefer_low = audioParams.prefer_low; end
                if isfield(audioParams, 'nfft'),        preParams.nfft = audioParams.nfft; end
                if isfield(audioParams, 'ovPerc'),      preParams.ovPerc = audioParams.ovPerc; end
                if isfield(audioParams, 'fmax'),        preParams.fmax = audioParams.fmax; end
                if isfield(audioParams, 'order'),       preParams.order = audioParams.order; end
            end
        catch
        end
    end
        
end

% === Auto-Analyse nach Laden der results_*.mat ============================
AUTO_ANALYZE_ON_LOAD = true;   % optional als global/Config

%% Video-/Audio-Pfade (aus recordResult.metadata, mit Legacy-Fallback)
videoPath = "";
audioPath = "";

if isfield(recordResult,'metadata') && isstruct(recordResult.metadata)
    if isfield(recordResult.metadata,'video'),   videoPath = string(recordResult.metadata.video); end
    if isfield(recordResult.metadata,'audio'),   audioPath = string(recordResult.metadata.audio); end
end
% Legacy-Fallback (für ältere MAT-Dateien):
if videoPath=="" && isfield(recordResult,'video'), videoPath = string(recordResult.video); end
if audioPath=="" && isfield(recordResult,'audio'), audioPath = string(recordResult.audio); end

LOG('Video: %s', string(videoPath));
LOG('Audio: %s', string(audioPath));

if strlength(videoPath)==0 || ~isfile(videoPath)
    error('Videodatei nicht gefunden. Erwartet unter recordResult.metadata.video (Fallback: recordResult.video).');
end

% Audio ggf. aus Video extrahieren (unverändert beibehalten)
if strlength(audioPath)==0 || ~isfile(audioPath)
    LOG('Audio fehlt oder ungueltig -> versuche aus Video zu lesen …');
    try
        [~,~,ext] = fileparts(videoPath);
        if any(strcmpi(ext,{'.mp4','.m4a','.mov','.m4v'}))
            [ya,fa] = audioread(videoPath);
            if size(ya,2)>1, ya = mean(ya,2); end
            ya = double(ya(:));
            tmpWav = fullfile(tempdir, ['tmp_audio_', char(java.util.UUID.randomUUID), '.wav']);
            audiowrite(tmpWav, ya, fa);
            audioPath = tmpWav;
            LOG('Audio extrahiert nach: %s', audioPath);
        else
            error('Keine Audiodatei gefunden und Audio-Extraktion nicht möglich.')
        end
    catch ME
        warning(ME.identifier, 'Audio konnte nicht aus dem Video gelesen werden: %s', ME.message);
        audioPath = '';
    end
end

LOG('Video: %s', string(videoPath));
LOG('Audio: %s', string(audioPath));

if isempty(videoPath) || ~isfile(videoPath)
    error('Videodatei nicht gefunden. recordResult.* enthält keinen gültigen Pfad.');
end

% Audio ggf. aus Video extrahieren
if isempty(audioPath) || ~isfile(audioPath)
    LOG('Audio fehlt oder ungueltig -> versuche aus Video zu lesen …');
    try
        [~,~,ext] = fileparts(videoPath);
        if any(strcmpi(ext,{'.mp4','.m4a','.mov','.m4v'}))
            [ya,fa] = audioread(videoPath);
            if size(ya,2)>1, ya = mean(ya,2); end
            ya = double(ya(:));                         % <-- NEU
            tmpWav = fullfile(tempdir, ['tmp_audio_', char(java.util.UUID.randomUUID), '.wav']);
            audiowrite(tmpWav, ya, fa);
            audioPath = tmpWav;
            LOG('Audio extrahiert nach: %s', audioPath);
        else
            error('Keine Audiodatei gefunden und Audio-Extraktion nicht möglich.')
        end
    catch ME
        warning(ME.identifier, 'Audio konnte nicht aus dem Video gelesen werden: %s', ME.message);
        audioPath = '';
    end
end

%% Video/Audio laden
v = VideoReader(videoPath);
vidDuration = v.Duration;
vidFPS = v.FrameRate;
vidWH = [v.Width v.Height];
LOG('Video: %.3fs @ %.3f fps, %dx%d', vidDuration, vidFPS, vidWH(1), vidWH(2));

y = []; fs = [];
if ~isempty(audioPath) && isfile(audioPath)
    [y, fs] = audioread(audioPath);

    % nach: [y, fs] = audioread(audioPath);
    if size(y,2) > 1, y = mean(y,2); end % Mono für Plot/Sync
    y = double(y(:));                           % <-- NEU: Spaltenvektor erzwingen
    y_init = y; fs_init = fs; audioPath_init = audioPath;   % Snapshot für Restore

    LOG('Audio: %d Samples @ %d Hz', numel(y), fs);
else
    LOG('Kein Audio geladen.');
end

%% UI — FINAL DROP-IN (OCR clean; Audio/RPM mit Offsets & Overlays)

% (Optional) Workaround gegen seltene Java-Tooltip-NPEs
try
    javax.swing.ToolTipManager.sharedInstance.setEnabled(false); 
catch
end

% === UI & Layout ===
fig = uifigure('Name','OCR Extractor (Script)','Position',[50 50 1280 820]);

% Top-Level Tabs
tgMain  = uitabgroup(fig);
tgMain.Position = [0 0 fig.Position(3) fig.Position(4)];

% ============================================================
% TAB 1: OCR  (nur Video/ROIs/Run OCR – KEIN Audio im OCR-Tab)
% ============================================================
tabOCR  = uitab(tgMain,'Title','OCR');
gl      = uigridlayout(tabOCR,[12 12]);
% Mehr Platz unten für Live-OCR, ROI kleiner:
gl.RowHeight   = {30, 36, 36, 36, 36, 22, '1x','1x', 28, 120, 120, 40};
gl.ColumnWidth = {'3x','3x','3x','3x','1x','1x','1x','1x','2x','2x','2x','2x'};

% Statuszeile
lblStatus = uilabel(gl,'Text','Bereit');  lblStatus.Layout.Row = 1;  lblStatus.Layout.Column = [1 12];

% Progressbar (Fallback)
pbPanel = uipanel(gl,'BorderType','line','BackgroundColor',[0.97 0.97 0.97]);
pbPanel.Layout.Row = 6;   pbPanel.Layout.Column = [1 8];   pbPanel.Visible = 'off';
pbFill  = uipanel(pbPanel,'BackgroundColor',[0 0.4470 0.7410],'Position',[1 1 0 18]);
pbLabel = uilabel(pbPanel,'Text','', 'HorizontalAlignment','center','FontWeight','bold');
pbLabel.Position = [1 1 100 18];
pbValue = 0;
% pbPanel.SizeChangedFcn = @(~,~) layoutPb(); -> warning jedes mal, daher disabled
function layoutPb()
    posp = pbPanel.Position; w = max(1, floor(pbValue * max(1,posp(3)-2))); h = max(1, posp(4)-2);
    pbFill.Position  = [1 1 w h]; pbLabel.Position = [1 1 posp(3) posp(4)];
end
function pbShow(tf), if tf, pbPanel.Visible='on'; else, pbPanel.Visible='off'; end, end
function pbSet(val, msg)
    pbValue = max(0,min(1,double(val))); layoutPb();
    if nargin>=2 && ~isempty(msg), pbLabel.Text = sprintf('%s  (%3.0f%%)', msg, pbValue*100);
    else,                           pbLabel.Text = sprintf('%3.0f%%', pbValue*100); end
    drawnow limitrate;
end

% === Controls (oben) — NUR Start/Ende/Play (Offset erst im Audio-Tab) ===
tmp = uilabel(gl,'Text','Start [s]'); tmp.Layout.Row = 2;  tmp.Layout.Column = 1;
sldStart = uislider(gl,'Limits',[0 max(vidDuration,eps)],'Value',0); sldStart.Layout.Row = 2;  sldStart.Layout.Column = [2 7];
lblStartVal = uilabel(gl,'Text','0.00 s','HorizontalAlignment','right'); lblStartVal.Layout.Row = 2;  lblStartVal.Layout.Column = 8;

tmp = uilabel(gl,'Text','Ende [s]'); tmp.Layout.Row = 3;  tmp.Layout.Column = 1;
sldEnd = uislider(gl,'Limits',[0 max(vidDuration,eps)],'Value',vidDuration); sldEnd.Layout.Row = 3;  sldEnd.Layout.Column = [2 7];
lblEndVal = uilabel(gl,'Text',sprintf('%.2f s', vidDuration),'HorizontalAlignment','right'); lblEndVal.Layout.Row = 3;  lblEndVal.Layout.Column = 8;

btnPlay  = uibutton(gl,'push','Text','Play','ButtonPushedFcn',@onPlayPause); btnPlay.Layout.Row = 5;  btnPlay.Layout.Column = 1;
lblNow   = uilabel(gl,'Text','t = 0.00 s');  lblNow.Layout.Row   = 5;  lblNow.Layout.Column   = [2 3];
lblFrame = uilabel(gl,'Text','Frame = 1/1'); lblFrame.Layout.Row = 5;  lblFrame.Layout.Column = [4 5];

mt = unique(round([0, vidDuration/4, vidDuration/2, 3*vidDuration/4, vidDuration],1));
sldStart.MajorTicks = mt;  sldStart.MajorTickLabels = string(mt);
sldEnd.MajorTicks   = mt;  sldEnd.MajorTickLabels   = string(mt);

% === Video (mittig, Reihen 7–8) ===
axVid = uiaxes(gl);
axVid.Layout.Row = [7 12];   axVid.Layout.Column = [1 8];
axVid.Toolbar.Visible = 'off';  axVid.XTick = [];  axVid.YTick = [];
title(axVid, string(videoPath), 'Interpreter','none');
v.CurrentTime = 0;  frame = readFrame(v);
hImg = imshow(frame, 'Parent', axVid);  axis(axVid,'image');  hold(axVid,'on');

% === ROIs rechts (kleiner) ===
tmp = uilabel(gl,'Text','ROIs'); tmp.Layout.Row = 2;  tmp.Layout.Column = 9;
tbl = uitable(gl); tbl.Layout.Row = [2 6];  tbl.Layout.Column = [9 12];
tbl.ColumnName = {'name_roi','roi','fmt','pattern','max_scale'}; tbl.RowName = {}; tbl.ColumnEditable = [true false true true true];

btnAddROI = uibutton(gl,'push','Text','ROI hinzufügen','ButtonPushedFcn',@onAddROI); btnAddROI.Layout.Row=7;  btnAddROI.Layout.Column=[9 10];
btnDelROI = uibutton(gl,'push','Text','Ausgewählte ROI löschen','ButtonPushedFcn',@onDelROI); btnDelROI.Layout.Row=7;  btnDelROI.Layout.Column=[11 12];

% Live-OCR (größer, oberhalb Run OCR)
tblLive = uitable(gl);
tblLive.Layout.Row    = [8 11];   % <-- vergrößert
tblLive.Layout.Column = [9 12];
tblLive.ColumnName    = {'name_roi','last_text'}; tblLive.RowName = {}; tblLive.ColumnEditable= [false false];

% --- Strecke (OCR-Tab) — ddTrack + cbNBR (ZEILE 3, rechts) ---
tmp = uilabel(gl,'Text','Strecke','HorizontalAlignment','right');
tmp.Layout.Row = 4; 
tmp.Layout.Column = 1;

ddTrack = uidropdown(gl, ...
    'Items', { ...
        '(keine)', ...
        'Nürburgring Nordschleife (20 832 m)', ...
        'Hockenheimring (4 574 m)' ...
    }, ...
    'Value','(keine)');
ddTrack.Layout.Row    = 4;
ddTrack.Layout.Column = [2 3];
ddTrack.Tag = 'ddTrack';

btnPrepareOCR = uibutton(gl,'push','Text','OCR vorbereiten','ButtonPushedFcn',@startupOCR);
btnPrepareOCR.Layout.Row  = 12;
btnPrepareOCR.Layout.Column = [9 10];   % frei wählen
btnPrepareOCR.Enable = 'off';

% OCR-Button
btnRunOCR = uibutton(gl,'push','Text','Run OCR (Start→End)','ButtonPushedFcn',@onRunOCR);
btnRunOCR.Layout.Row  = 12;  btnRunOCR.Layout.Column=[11 12]; btnRunOCR.Enable = 'off';

% Callback-Verkabelung (sofern vorhanden)
sldStart.ValueChangingFcn = @(src,evt) onStartChanged(evt.Value);
sldEnd.ValueChangingFcn   = @(src,evt) onEndChanged(evt.Value);
tbl.SelectionChangedFcn   = @onTblSelectionChanged;

% =====================================================================
% TAB 2: Audio / RPM  (Offset + a/v + Audio/Spektrogramm + Overlays)
% =====================================================================
tabAudio = uitab(tgMain,'Title','Audio / RPM');

glAudio  = uigridlayout(tabAudio,[4 6]);
glAudio.RowHeight   = {'fit', 120, '1x', '1x'};  % Header wächst automatisch; Audio kompakt
glAudio.ColumnWidth = {'1x','1x','1x','1x','1x','1x'};

% Header (3 Zeilen x 14 Spalten, kompakt)
hdr = uigridlayout(glAudio,[3 15]); hdr.Layout.Row = 1;  hdr.Layout.Column = [1 6];
hdr.RowHeight = {26, 26, 30}; hdr.ColumnWidth = repmat({'1x'},1,15);

% Zeile 1: FFT/Einstellungen
tmp = uilabel(hdr,'Text','NFFT','HorizontalAlignment','right');  tmp.Layout.Row=1; tmp.Layout.Column=1;
edtNFFT2 = uieditfield(hdr,'numeric','Value',8192);               edtNFFT2.Layout.Row=1; edtNFFT2.Layout.Column=2;
tmp = uilabel(hdr,'Text','Overlap [%]','HorizontalAlignment','right'); tmp.Layout.Row=1; tmp.Layout.Column=3;
edtOvPerc2 = uieditfield(hdr,'numeric','Value',75);               edtOvPerc2.Layout.Row=1; edtOvPerc2.Layout.Column=4;
tmp = uilabel(hdr,'Text','f max [Hz]','HorizontalAlignment','right');  tmp.Layout.Row=1; tmp.Layout.Column=5;
edtFmax2 = uieditfield(hdr,'numeric','Value',1000);               edtFmax2.Layout.Row=1;  edtFmax2.Layout.Column=6;
tmp = uilabel(hdr,'Text','Zyl','HorizontalAlignment','right');    tmp.Layout.Row=1; tmp.Layout.Column=7;
edtCyl2 = uieditfield(hdr,'numeric','Value',8);                   edtCyl2.Layout.Row=1;  edtCyl2.Layout.Column=8;
tmp = uilabel(hdr,'Text','Takt','HorizontalAlignment','right');   tmp.Layout.Row=1; tmp.Layout.Column=9;
edtStroke2 = uieditfield(hdr,'numeric','Value',4);                edtStroke2.Layout.Row=1; edtStroke2.Layout.Column=10;
tmp = uilabel(hdr,'Text','Ordnung','HorizontalAlignment','right'); tmp.Layout.Row=1; tmp.Layout.Column=11;
edtOrd2 = uieditfield(hdr,'numeric','Value',1);                   edtOrd2.Layout.Row=1;  edtOrd2.Layout.Column=12;

% Zeile 2: RPM & Getriebe
tmp = uilabel(hdr,'Text','RPM min','HorizontalAlignment','right'); tmp.Layout.Row=2; tmp.Layout.Column=1;
edtRpmMin2 = uieditfield(hdr,'numeric','Value',3000);              edtRpmMin2.Layout.Row=2; edtRpmMin2.Layout.Column=2;
tmp = uilabel(hdr,'Text','RPM max','HorizontalAlignment','right'); tmp.Layout.Row=2; tmp.Layout.Column=3;
edtRpmMax2 = uieditfield(hdr,'numeric','Value',7500);              edtRpmMax2.Layout.Row=2; edtRpmMax2.Layout.Column=4;
tmp = uilabel(hdr,'Text','r_{dyn} [m]','HorizontalAlignment','right'); tmp.Layout.Row=2; tmp.Layout.Column=5;
edtRdyn2 = uieditfield(hdr,'numeric','Value',0.35);                edtRdyn2.Layout.Row=2;   edtRdyn2.Layout.Column=6;

cbUseOCRv2 = uicheckbox(hdr,'Text','OCR-v nutzen','Value',true);  cbUseOCRv2.Layout.Row=2; cbUseOCRv2.Layout.Column=7;
cbLowGear2 = uicheckbox(hdr, ...
    'Text','niedrigster Gang bevorzugt', ...
    'Value',false);
cbLowGear2.Layout.Row = 2;
cbLowGear2.Layout.Column = 15;
btnGearing = uibutton(hdr,'Text','Getriebe …');                    btnGearing.Layout.Row=2; btnGearing.Layout.Column=[8 9];
btnRunRPM2 = uibutton(hdr,'Text','Analyse RPM');                   btnRunRPM2.Layout.Row=2; btnRunRPM2.Layout.Column=[11 12];
btnRunRPM2.Enable = 'on';           % kann bleiben
btnRunRPM2.Tooltip = 'Manuell neu analysieren (Automatik läuft bei jeder Änderung)';

cbNBR = uicheckbox(hdr, ...
    'Text','Streckenlänge korrigieren', ...
    'Value', false, ...
    'Enable','off');
cbNBR.Layout.Row    = 1;
cbNBR.Layout.Column = 15;
cbNBR.Tag = 'cbNBR';

ddTrack.ValueChangedFcn = @(src,evt) toggleCbNBR(src, cbNBR);
if ~strcmp(ddTrack.Value,'(keine)'), cbNBR.Enable = 'on'; else, cbNBR.Enable = 'off'; end

% Toleranz in % für v->Gang Matching
tmp = uilabel(hdr,'Text','Tol ±[%]','HorizontalAlignment','right'); 
tmp.Layout.Row=2; tmp.Layout.Column=13;
edtTolPct2 = uieditfield(hdr,'numeric','Value',6);  % z.B. ±6 %
edtTolPct2.Layout.Row=2; edtTolPct2.Layout.Column=14;


% Zeile 3: Postprocessing (Offset + a/v-Grenzen) — AKTIV
tmp = uilabel(hdr,'Text','Audio Offset [s]','HorizontalAlignment','right'); tmp.Layout.Row=3; tmp.Layout.Column=1;
sldOff = uislider(hdr,'Limits',[-5 5],'Value',0,'ValueChangingFcn',@(src,evt)updateOffset(evt.Value));
sldOff.Layout.Row=3; sldOff.Layout.Column=[2 5];
lblOffVal = uilabel(hdr,'Text','0.00 s','HorizontalAlignment','right'); lblOffVal.Layout.Row=3; lblOffVal.Layout.Column=6;
sldOff.MajorTicks = -5:1:5;  sldOff.MajorTickLabels = string(-5:1:5);

tmp = uilabel(hdr,'Text','a min','HorizontalAlignment','right'); tmp.Layout.Row=3; tmp.Layout.Column=7;
accMinEdit = uieditfield(hdr,'numeric','Value',-10);              accMinEdit.Layout.Row=3; accMinEdit.Layout.Column=8;
tmp = uilabel(hdr,'Text','a max','HorizontalAlignment','right'); tmp.Layout.Row=3; tmp.Layout.Column=9;
accMaxEdit = uieditfield(hdr,'numeric','Value', 10);              accMaxEdit.Layout.Row=3; accMaxEdit.Layout.Column=10;
tmp = uilabel(hdr,'Text','v min [km/h]','HorizontalAlignment','right'); tmp.Layout.Row=3; tmp.Layout.Column=11;
vMinEdit = uieditfield(hdr,'numeric','Value',50);                 vMinEdit.Layout.Row=3; vMinEdit.Layout.Column=12;
tmp = uilabel(hdr,'Text','v max [km/h]','HorizontalAlignment','right'); tmp.Layout.Row=3; tmp.Layout.Column=13;
vMaxEdit = uieditfield(hdr,'numeric','Value',300);                vMaxEdit.Layout.Row=3; vMaxEdit.Layout.Column=14;

% --- Zeile 2: Audioplot (kompakt)
axAud = uiaxes(glAudio); axAud.Layout.Row = 2;  axAud.Layout.Column = [1 6];
title(axAud,'Audio'); xlabel(axAud,'Zeit [s]'); ylabel(axAud,'Amplitude'); grid(axAud,'on'); hold(axAud,'on');

% --- Zeile 3: Spektrogramm (links) & RPM (rechts) [FALLBACK LAYOUT]
axSpec2 = uiaxes(glAudio);  axSpec2.Layout.Row=3; axSpec2.Layout.Column=[1 3];
title(axSpec2,'Spektrogramm'); ylabel(axSpec2,'f [Hz]'); xlabel(axSpec2,'t [s]');
grid(axSpec2,'on'); %hold(axSpec2,'on');

axRPM2  = uiaxes(glAudio);  axRPM2.Layout.Row=3; axRPM2.Layout.Column=[4 6];
title(axRPM2,'RPM'); ylabel(axRPM2,'U/min'); xlabel(axRPM2,'t [s]');
grid(axRPM2,'on'); hold(axRPM2,'on');


% --- Zeile 4: v (links) & Gang (rechts)
axV2    = uiaxes(glAudio);  axV2.Layout.Row=4; axV2.Layout.Column=[1 3];
title(axV2,'v [km/h]'); ylabel(axV2,'km/h'); xlabel(axV2,'t [s]'); grid(axV2,'on'); hold(axV2,'on');
axGear2 = uiaxes(glAudio);  axGear2.Layout.Row=4; axGear2.Layout.Column=[4 6];
title(axGear2,'Gang'); ylabel(axGear2,'#'); xlabel(axGear2,'t [s]'); grid(axGear2,'on'); hold(axGear2,'on');

% --- Audio-Kurve + Sync-Linien auf axAud ---
hAud = gobjects(0);  hStart = gobjects(0);  hEnd = gobjects(0);  hSync = gobjects(0);
if exist('y','var') && exist('fs','var') && ~isempty(y) && ~isempty(fs) && isvector(y) && fs>0
    tAud = (0:numel(y)-1)/fs;
    hAud = plot(axAud, tAud, double(y(:)), 'HitTest','off');
    xlim(axAud, [0 max(tAud)]);
end
hStart = xline(axAud, sldStart.Value, '--','Start','LabelVerticalAlignment','bottom','LabelOrientation','horizontal');
hEnd   = xline(axAud, sldEnd.Value,   '--','End',  'LabelVerticalAlignment','bottom','LabelOrientation','horizontal');

% --- Spektrogramm & Overlays (Handles, werden später befüllt) ---
hSpecImg    = gobjects(1);      % imagesc-Handle des Spektrogramms (bitte beim Plotten setzen)

% --- Sync-Linie im Audio-Plot (bezogen auf Offset)
audioOffset = 0;  % globaler Zustand für Shifts
hSync  = xline(axAud, sldStart.Value + audioOffset, '-', 'Sync','LabelVerticalAlignment','top','LabelOrientation','horizontal');

% Button-Callbacks im Audio-Tab
btnGearing.ButtonPushedFcn = @(~,~)openGearingDialogTable;
btnRunRPM2.ButtonPushedFcn = @onRunRPM2;

% FFT/Anzeige
edtNFFT2.ValueChangedFcn   = @(~,~) reanalyzeAndSave();
edtOvPerc2.ValueChangedFcn = @(~,~) reanalyzeAndSave();
edtFmax2.ValueChangedFcn   = @(~,~) reanalyzeAndSave();
edtCyl2.ValueChangedFcn    = @(~,~) reanalyzeAndSave();
edtStroke2.ValueChangedFcn = @(~,~) reanalyzeAndSave();
edtOrd2.ValueChangedFcn    = @(~,~) reanalyzeAndSave();

% RPM/Gearing
edtRpmMin2.ValueChangedFcn = @(~,~) reanalyzeAndSave();
edtRpmMax2.ValueChangedFcn = @(~,~) reanalyzeAndSave();
edtRdyn2.ValueChangedFcn   = @(~,~) reanalyzeAndSave();
cbUseOCRv2.ValueChangedFcn = @(~,~) reanalyzeAndSave();
cbLowGear2.ValueChangedFcn = @(~,~) reanalyzeAndSave();

% Offset + Filtergrenzen
% (updateOffset() lässt visuell “live” laufen; Analyse bei “loslassen”)
sldOff.ValueChangedFcn     = @(~,~) reanalyzeAndSave();
accMinEdit.ValueChangedFcn = @(~,~) reanalyzeAndSave();
accMaxEdit.ValueChangedFcn = @(~,~) reanalyzeAndSave();
vMinEdit.ValueChangedFcn   = @(~,~) reanalyzeAndSave();
vMaxEdit.ValueChangedFcn   = @(~,~) reanalyzeAndSave();


%% =====================================================================
% TAB 3: Vergleich (Messdatei vs. Auswertung)
% =====================================================================
tabCmp = uitab(tgMain,'Title','Vergleich');
GL = uigridlayout(tabCmp,[4 6]);
GL.RowHeight   = {'fit', '1x', '1x', 'fit'};
GL.ColumnWidth = {'1x','1x','1x','1x','1x','1x'};

% --- Kopfzeile / Controls ---
hdr3 = uigridlayout(GL,[3 12]); 
hdr3.Layout.Row=1; hdr3.Layout.Column=[1 6];
hdr3.RowHeight   = {24, 24, 24, 24};
hdr3.ColumnWidth = repmat({'1x'},1,12);

btnLoadTT = uibutton(hdr3,'Text','MAT laden (TT)');
btnLoadTT.Layout.Row=1; btnLoadTT.Layout.Column=[1 2];

lblTTInfo = uilabel(hdr3,'Text','Keine Messdatei geladen');
lblTTInfo.Layout.Row=1; lblTTInfo.Layout.Column=[3 12];

temp = uilabel(hdr3,'Text','TT Spalte v [km/h]','HorizontalAlignment','right');
temp.Layout.Row = 2;
temp.Layout.Column = 1;
ddTTv   = uidropdown(hdr3,'Items',{},'Enable','off');
ddTTv.Layout.Row=2; ddTTv.Layout.Column=[2 4];

temp = uilabel(hdr3,'Text','TT Spalte RPM','HorizontalAlignment','right');
temp.Layout.Row = 2;
temp.Layout.Column = 5;
ddTTn   = uidropdown(hdr3,'Items',{},'Enable','off');
ddTTn.Layout.Row=2; ddTTn.Layout.Column=[6 8];

temp = uilabel(hdr3,'Text','Zeit-Offset [s]','HorizontalAlignment','right');
temp.Layout.Row = 3;
temp.Layout.Column = 1;
sldCmpOff = uislider(hdr3,'Limits',[-30 30],'Value',0);
sldCmpOff.Layout.Row=3; sldCmpOff.Layout.Column=[2 7];
lblCmpOff = uilabel(hdr3,'Text','0.00 s');
lblCmpOff.Layout.Row=3; lblCmpOff.Layout.Column=8;

% --- Toleranzen & Bezug (Geschwindigkeit)
temp = uilabel(hdr3,'Text','Tol v [km/h]','HorizontalAlignment','right');
temp.Layout.Row = 2; 
temp.Layout.Column = 9;
edtTolV = uieditfield(hdr3,'numeric','Value',5);          % z.B. 5 %
edtTolV.Layout.Row      = 2; 
edtTolV.Layout.Column   = 10;
temp = uilabel(hdr3,'Text','Bezug v:','HorizontalAlignment','right');
temp.Layout.Row     = 2;
temp.Layout.Column  = 11; 
ddRefV  = uidropdown(hdr3,'Items',{'Messdatei','Auswertung'},'Value','Messdatei');
ddRefV.Layout.Row   = 2; 
ddRefV.Layout.Column= 12;   

% --- Toleranzen & Bezug (Drehzahl)
temp = uilabel(hdr3,'Text','Tol n [rpm]','HorizontalAlignment','right');
temp.Layout.Row = 3; 
temp.Layout.Column = 9;
edtTolN = uieditfield(hdr3,'numeric','Value',3);          % z.B. 3 %
edtTolN.Layout.Row      = 3; 
edtTolN.Layout.Column   = 10;
temp = uilabel(hdr3,'Text','Bezug n:','HorizontalAlignment','right');
temp.Layout.Row     = 3;
temp.Layout.Column  = 11; 
ddRefN  = uidropdown(hdr3,'Items',{'Messdatei','Auswertung'},'Value','Messdatei');
ddRefN.Layout.Row   = 3; 
ddRefN.Layout.Column= 12;

% --- Auto-Refresh bei Toleranz-/Bezug-Änderung ---
edtTolV.ValueChangedFcn = @(~,~) updateComparison();
edtTolN.ValueChangedFcn = @(~,~) updateComparison();
ddRefV.ValueChangedFcn  = @(~,~) updateComparison();
ddRefN.ValueChangedFcn  = @(~,~) updateComparison();

% --- OCR-Auswahl (Zeile 4): Spalten aus OCR für v & n ---
tmp = uilabel(hdr3,'Text','OCR Spalte v [km/h]','HorizontalAlignment','right');
tmp.Layout.Row = 4; tmp.Layout.Column = 1;
ddOCRv = uidropdown(hdr3,'Items',{},'Enable','off');
ddOCRv.Layout.Row = 4; ddOCRv.Layout.Column = [2 4];

tmp = uilabel(hdr3,'Text','OCR Spalte RPM','HorizontalAlignment','right');
tmp.Layout.Row = 4; tmp.Layout.Column = 5;
ddOCRn = uidropdown(hdr3,'Items',{},'Enable','off');
ddOCRn.Layout.Row = 4; ddOCRn.Layout.Column = [6 8];

cbUseOCRn = uicheckbox(hdr3,'Text','OCR-RPM verwenden','Value',true,'Enable','off');
cbUseOCRn.Layout.Row = 4; cbUseOCRn.Layout.Column = [9 12];

% Reagieren auf Auswahländerung
ddOCRv.ValueChangedFcn = @(~,~) updateComparison();
ddOCRn.ValueChangedFcn = @(~,~) updateComparison();
cbUseOCRn.ValueChangedFcn= @(~,~) updateComparison();

btnCmpRun = uibutton(hdr3,'Text','Vergleich aktualisieren');
btnCmpRun.Layout.Row=1; btnCmpRun.Layout.Column=[9 10];
btnCmpRun.Enable = 'off';   % <-- neu: nur klickbar, wenn TT geladen

% --- Plots ---
axCmpV = uiaxes(GL); axCmpV.Layout.Row=2; axCmpV.Layout.Column=[1 6];
title(axCmpV,'Geschwindigkeit'); xlabel(axCmpV,'t [s]'); ylabel(axCmpV,'km/h');
grid(axCmpV,'on'); hold(axCmpV,'on');

axCmpN = uiaxes(GL); axCmpN.Layout.Row=3; axCmpN.Layout.Column=[1 6];
title(axCmpN,'Drehzahl'); xlabel(axCmpN,'t [s]'); ylabel(axCmpN,'1/min');
grid(axCmpN,'on'); hold(axCmpN,'on');

% --- Statuszeile ---
lblHit = uilabel(GL,'Text','Trefferquote v: —   |   Trefferquote n: —');
lblHit.Layout.Row=4; lblHit.Layout.Column=[1 6];

% --- Zustand ---
TT_meas   = [];     % timetable aus Messdatei
% (Lokale Handles werden nicht benötigt)

% --- Verdrahtung ---
btnLoadTT.ButtonPushedFcn = @(~,~) onLoadTT();
btnCmpRun.ButtonPushedFcn = @(~,~) updateComparison();
sldCmpOff.ValueChangingFcn = @(~,e) set(lblCmpOff,'Text',sprintf('%.2f s',e.Value));
sldCmpOff.ValueChangedFcn  = @(~,~) updateComparison();
ddTTv.ValueChangedFcn      = @(~,~) updateComparison();
ddTTn.ValueChangedFcn      = @(~,~) updateComparison();
setappdata(fig,'fnUpdateComparison', @updateComparison);

% Auto-Restore der letzten TT + Vergleich fahren
try
    restoreCmpFromValidation();
catch
end

%% Params
ocrInfos = struct();

%% ROI-Setlist
roiNames = {'_', ...
    't_s','v_Fzg_kmph','v_Fzg_mph', ...
    'numgear_GET', ...
    'a_G','a_mps2', ...
    'a_x_G','a_x_pos_G','a_x_neg_G','a_x_mps', ...
    'a_y_G','a_y_pos_G','a_y_neg_G','a_y_mps', ...
    'P_kW','M_Nm','n_mot_Upmin', ...
    'M_VL_Nm','M_VR_Nm','M_HL_Nm','M_HR_Nm', ...
    'stellung_gaspedal_proz','stellung_bremspedal_proz', ...
    'track_minimap'};
fmtOptions = {
    'any', ...                      % keine Prüfung
    'time_m:ss', ...                % 2:17
    'time_m:ss.S', ...              % 2:17.9
    'time_m:ss.SS', ...             % 2:17.96
    'time_m:ss.SSS', ...            % 2:17.960
    'time_m:ss.SSSS', ...           % 2:17.9602
    'time_m:ss.SSSSSS', ...         % 2:17.960243
    'time_mm:ss', ...               % 02:17
    'time_mm:ss.S', ...             % 02:17.9
    'time_mm:ss.SS', ...            % 02:17.96
    'time_mm:ss.SSS', ...           % 02:17.960
    'time_mm:ss.SSSS', ...          % 02:17.9602
    'time_mm:ss.SSSSSS', ...        % 02:17.960243
    'time_hh:mm:ss', ...            % 00:02:17
    'time_hh:mm:ss.S', ...          % 00:02:17.9
    'time_hh:mm:ss.SS', ...         % 00:02:17.96
    'time_hh:mm:ss.SSS', ...        % 00:02:17.960
    'time_hh:mm:ss.SSSS', ...       % 00:02:17.9602
    'time_hh:mm:ss.SSSSSS', ...     % 00:02:17.960243
    'integer', ...
    'int_1', ...
    'int_2', ...
    'int_3', ...
    'int_4', ...
    'int_min2_max3', ...
    'int_min3_max4', ...
    'float', ...
    'alnum', ...
    'custom'
    };                  % benutzerdefinierte Regex in 'pattern'

% Leere Tabelle mit festen Kategorien
name_init = categorical(strings(0,1), roiNames);
fmt_init  = categorical(strings(0,1), fmtOptions);
T = table(name_init, strings(0,1), fmt_init, strings(0,1), ones(0,1), ...
          'VariableNames', {'name_roi','roi','fmt','pattern','max_scale'});
tbl.Data = T;

% Eingaben validieren (Scale numerisch halten etc.)
tbl.CellEditCallback = @onTblEdited;

% Live-OCR-Status-Tabelle (rechts unter der ROI-Tabelle)
% tblLive = uitable(gl);
% tblLive.Layout.Row    = [10 11];   % Live-Tabelle nur Zeilen 10–11
% tblLive.Layout.Column = [9 12];
% tblLive.ColumnName    = {'name_roi','last_text'};
% tblLive.RowName       = {};
% tblLive.ColumnEditable= [false false];
tblLive.Data          = table(categorical(strings(0,1),roiNames), string([]), ...
                              'VariableNames', {'name_roi','last_text'});

% Container für Rects/Listener
rects = struct('h',{},'el',{});

% Playback-State
isPlaying = false;
t0 = [];               % tic-Start für laufende Session
tmr = []; ap = [];     % timer + audioplayer
lastTickLog = -Inf;    % Debug-Takt

% OCR-Status
isOCRRunning = false;
ocrAbortRequested = false;

% NEU: Basiszeit & Resume
tBaseAbs   = 0;        % absolute Startzeit der aktuellen Play-Session
tResumeAbs = NaN;      % wohin beim nächsten Play gesprungen wird

% Getriebe-Status (global im Funktions-Workspace)
gearing = struct('axle',4.059, 'gears',[3.56 2.53 1.68 1.02 0.79 0.76 0.63]);


%% Callbacks/Init
sldStart.ValueChangingFcn = @(src,evt) onStartChanged(evt.Value);
sldEnd.ValueChangingFcn   = @(src,evt) onEndChanged(evt.Value);

tbl.SelectionChangedFcn = @onTblSelectionChanged;

% Button verdrahten
btnGearing.ButtonPushedFcn = @(~,~)openGearingDialogTable;
btnRunRPM2.ButtonPushedFcn = @onRunRPM2;

onStartEndChanged(sldStart.Value, sldEnd.Value);
LOG('UI fertig initialisiert.');

% --- Vorbelegte Parameter anwenden (falls vorhanden)
if exist('preParams','var') && ~isempty(preParams)
    applyPreloadParams(preParams);
end

% ======= Auto: RPM-Ansicht beim Start (immer kompletter Aufbau) =======
if ANALYZE_RPM_ON_START
    try
        if ~isempty(y) && ~isempty(fs) && fs > 0
            onRunRPM2();   % baut Spektrogramm, RPM, v[km/h] und Gang vollständig auf
        end
    catch
        % still continue
    end
end

if AUTO_ANALYZE_ON_LOAD
    try
        % 1) Gespeicherte Parameter wiederherstellen (falls vorhanden)
        if exist('S','var')
            try
                if isfield(S,'recordResult') && isstruct(S.recordResult)
                    recordResult = S.recordResult;  % in Workspace übernehmen
                end
            catch
            end %#ok<*NOPRT>
            try
                if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'params')
                    params = recordResult.ocr.params; %#ok<NASGU>
                    % Falls du UI-Controls hattest, die aus params gesetzt werden:
                    % z.B.: ddTrack.Value = params.track; cbNBR.Value = params.useNBR; ...
                end
            catch
            end
            try populateOCRDropdowns(); catch, end
        end

        % 2) Nach Abschluss: Vergleichs-Tab aktualisieren (falls angelegt)
        try
            fUpd = getappdata(fig,'fnUpdateComparison');  % in Tab 3 gesetzt, siehe unten
            if isa(fUpd,'function_handle'), fUpd(); end
        catch
        end

    catch ME
        warning(ME.identifier, 'Auto-Analyse beim Laden fehlgeschlagen: %s', ME.message);
    end
end
% ======================================================================

updateRunButtonState();   % <— NEU

% ======================================================================
% CLI: falls gewünscht, OCR sofort starten
% ======================================================================
if cliRunOCR
    try
        % sicherstellen, dass der Button aktiviert ist:
        btnRunOCR.Enable = 'on';
        LOG('CLI: onRunOCR wurde automatisch gestartet.');
        onRunOCR();   % ohne Argumente -> CLI-Modus
    catch ME
        warning(ME.identifier, ...
            'CLI-OCR-Start fehlgeschlagen: %s', ME.message);
        
        % GUI schließen:
        try
            close(fig);
        catch
        end

        % % MATLAB sofort verlassen:
        % try
        %     error('CLI:OCRAbort','Automatischer OCR-Start fehlgeschlagen. Programm wird beendet.');
        % catch
        %     % Fallback, falls im Deployment:
        %     exit;   % beendet MATLAB/Skript
        % end
    end
end

%% Lokale Funktionen

% ===========================
% Hilfsfunktionen (Overlays)
% ===========================

    
    % Offset-Handling (verschiebt Spektrogramm + alle Overlays sofort mit)
    function updateOffset(val)
        % UI
        sldOff.Value = val; 
        lblOffVal.Text = sprintf('%.2f s', val);
    
        % Sync-Linie
        if isgraphics(hSync), hSync.Value = sldStart.Value + val; end
    
        % Δ nur relativ zur alten Einstellung anwenden
        delta = val - audioOffset;
    
        % Spektrogramm (imagesc hat 2-Element-XData)
        if isgraphics(hSpecImg)
            xd = get(hSpecImg,'XData');
            if numel(xd) >= 2
                set(hSpecImg,'XData', xd + delta);
            end
        end
    
        % Overlays sicher verschieben (ohne &&-Ketten)
        % shiftLineX(hRpmAudio,   delta);
        % shiftLineX(hRpmPred,    delta);
        % shiftLineX(hRpmPredHi,  delta);
        % shiftLineX(hRpmPredLo,  delta);
        % shiftLineX(hSpeedOnSpec,delta);
    
        % v- und Gang-Plot unten mitziehen
        for hh = [axV2.Children; axGear2.Children]'
            if isgraphics(hh) && isprop(hh,'XData')
                x = get(hh,'XData');
                if ~isempty(x)
                    set(hh,'XData', x + delta);
                end
            end
        end
    
        % Achsenfenster mitschieben
        axSpec2.XLim = axSpec2.XLim + delta;
        axAud.XLim   = axAud.XLim   + delta;
        axV2.XLim    = axV2.XLim    + delta;
        axGear2.XLim = axGear2.XLim + delta;

        try 
            axRPM2.XLim = axRPM2.XLim + delta; 
        catch
        end
    
        % Zustand merken
        audioOffset = val;
    end

    function shiftLineX(h, dx)
        % Verschiebt XData eines (oder mehrerer) Line-Handles robust um dx
        if isempty(h) || ~any(isgraphics(h))
            return
        end
        try
            xd = get(h, 'XData');
            if iscell(xd)        % mehrere Handles
                for k = 1:numel(h)
                    if ~isempty(xd{k})
                        set(h(k), 'XData', xd{k} + dx);
                    end
                end
            elseif ~isempty(xd)  % einzelner Handle
                set(h, 'XData', xd + dx);
            end
        catch
            % still & safe
        end
    end



    function onStartChanged(vStartNew)
        % clampen & übernehmen
        vStartNew = max(0, min(vStartNew, vidDuration));
        vEndNow   = max(vStartNew + 0.1, sldEnd.Value);   % End immer nach Start
        sldStart.Value = vStartNew; 
        sldEnd.Value   = min(vEndNow, vidDuration);
    
        % Marker updaten
        if ~isempty(hStart) && isgraphics(hStart), hStart.Value = vStartNew; end
        if ~isempty(hEnd) && isgraphics(hEnd),   hEnd.Value   = sldEnd.Value; end
        if ~isempty(hSync) && isgraphics(hSync),  hSync.Value  = vStartNew + sldOff.Value; end
    
        % **Video sofort auf Startposition zeigen**
        seekTo(vStartNew);

        if isPlaying
            startOrRestartAudioAt(vStartNew);
        end
    
        % Anzeige
        updateNowLabels(vStartNew, max(1, round(vStartNew*vidFPS)));
        lblStartVal.Text = sprintf('%.2f s', vStartNew);
        lblEndVal.Text   = sprintf('%.2f s', sldEnd.Value);
        LOG('Start verschoben: %.3f s (End=%.3f)', vStartNew, sldEnd.Value);

        if ~isPlaying
            tBaseAbs   = vStartNew;
            tResumeAbs = vStartNew;
        else
            tBaseAbs = vStartNew;      % laufend → Basis sofort ändern
            t0 = tic;
        end

    end
    
    function onEndChanged(vEndNew)
        % clampen & übernehmen
        vEndNew   = max(0, min(vEndNew, vidDuration));
        vStartNow = min(sldStart.Value, vEndNew - 0.1);
        sldStart.Value = max(0, vStartNow); 
        sldEnd.Value   = vEndNew;
    
        % Marker updaten
        if ~isempty(hStart) && isgraphics(hStart), hStart.Value = sldStart.Value; end
        if ~isempty(hEnd) && isgraphics(hEnd),   hEnd.Value   = vEndNew; end
        if ~isempty(hSync) && isgraphics(hSync),  hSync.Value  = sldStart.Value + sldOff.Value; end
    
        % **Video sofort auf Endposition (minus 1 Frame)**
        tShow = max(0, vEndNew - (1/vidFPS));
        seekTo(tShow);

        if isPlaying
            startOrRestartAudioAt(tShow);
        end
    
        % Anzeige
        updateNowLabels(tShow, max(1, round(tShow*vidFPS)));
        lblStartVal.Text = sprintf('%.2f s', sldStart.Value);
        lblEndVal.Text   = sprintf('%.2f s', vEndNew);
        LOG('Ende verschoben: %.3f s (Start=%.3f)', vEndNew, sldStart.Value);
    end
        
    function onTblSelectionChanged(src, evt)
        % Robust über MATLAB-Versionen hinweg: evt.Indices ODER src.Selection
        i = [];
        try
            if isprop(evt,'Indices')
                ind = evt.Indices;          % n×2 [row col]
                if ~isempty(ind), i = ind(1,1); end
            end
        catch
        end
        if isempty(i)
            try
                sel = src.Selection;        % n×2 [row col] (neuere Releases)
                if ~isempty(sel), i = sel(1,1); end
            catch 
            end
        end
        if isempty(i), return; end
        highlightSelected(i);
    end

    function seekTo(tAbs)
        % Sichere, ruckelfreie Anzeige eines Frames bei tAbs
        try
            v.CurrentTime = max(0, min(tAbs, vidDuration-1e-6));
            fr = readFrame(v);
            hImg.CData = fr;
        catch
            % Manche Container brauchen kleinen Offset
            try
                v.CurrentTime = max(0, min(tAbs+1e-3, vidDuration-1e-6));
                hImg.CData = readFrame(v);
            catch
                % Schweigend ignorieren
            end
        end
    end


    function onStartEndChanged(vStart, vEnd)
        vStart = max(0, min(vStart, vidDuration));
        vEnd   = max(0, min(vEnd, vidDuration));
        if vEnd <= vStart
            vEnd = min(vidDuration, vStart + 0.1);
        end
        sldStart.Value = vStart; sldEnd.Value = vEnd;
        if ~isempty(hStart) && isgraphics(hStart), hStart.Value = vStart; end
        if ~isempty(hEnd) && isgraphics(hEnd),   hEnd.Value   = vEnd;   end
        if ~isempty(hSync) && isgraphics(hSync),  hSync.Value  = vStart + sldOff.Value; end
        try
            v.CurrentTime = vStart;
            hImg.CData = readFrame(v);
        catch
        end
        updateNowLabels(vStart, 1);
        lblStartVal.Text = sprintf('%.2f s', vStart);
        lblEndVal.Text   = sprintf('%.2f s', vEnd);
        LOG('Start/End aktualisiert: [%.3f .. %.3f] s', vStart, vEnd);
    end


    function updateNowLabels(tNow, iFrame)
        nF = v.NumFrames; if isempty(nF), nF = round(vidDuration*vidFPS); end
        lblNow.Text = sprintf('t = %.2f s', tNow);
        lblFrame.Text = sprintf('Frame = %d/%d', iFrame, nF);
    end

    function onPlayPause(~,~)
        if ~isPlaying
            % --- START / RESUME ---
            isPlaying = true; btnPlay.Text = 'Pause';
    
            % Zielstart: vorhandene Resume-Zeit oder Start-Slider
            if ~isnan(tResumeAbs)
                tBaseAbs = max(0, min(tResumeAbs, vidDuration-1e-6));
            else
                tBaseAbs = sldStart.Value;
            end
    
            % Video auf tBaseAbs setzen und 1 Frame zeigen
            seekTo(tBaseAbs);
    
            % Audio vorbereiten (inkl. Offset)
            startOrRestartAudioAt(tBaseAbs);
    
            % Timer für Video
            t0 = tic;
            if ~isempty(tmr) && isvalid(tmr), stop(tmr); delete(tmr); end
            per = max(0.001, round(1000/vidFPS)/1000);  % auf 1 ms quantisiert
            tmr = timer('ExecutionMode','fixedRate','Period', per, ...
                        'TimerFcn', @onTick, 'StartDelay', 0);

            start(tmr);
            tResumeAbs = NaN;    % verbraucht
    
            LOG('Playback START: Base=%.3f, Ende=%.3f, Offset=%.2f', tBaseAbs, sldEnd.Value, sldOff.Value);
        else
            % --- PAUSE ---
            % aktuelle Zeit merken (Resume-Punkt)
            tResumeAbs = currentVideoAbs();
    
            isPlaying = false; btnPlay.Text = 'Play';
            if ~isempty(tmr) && isvalid(tmr), stop(tmr); delete(tmr); tmr = []; end
            % Audio sauber stoppen & freigeben
            if ~isempty(ap)
                try stop(ap); delete(ap); catch, end
                ap = [];
            end
            LOG('Playback PAUSE @ %.3f', tResumeAbs);
        end
    end


    function onTick(~,~)
        tRel = toc(t0);
        tNow = tBaseAbs + tRel;   % statt sldStart.Value + tRel

        if tNow >= sldEnd.Value || tNow >= vidDuration
            onPlayPause(); % stop
            return
        end
        try
            v.CurrentTime = tNow;
            hImg.CData = readFrame(v);
        catch
            onPlayPause();
            return
        end
        if ~isempty(hSync) && isgraphics(hSync)
            hSync.Value = tNow + sldOff.Value;
        end
        iFrame = max(1, round(tNow*vidFPS));
        updateNowLabels(tNow, iFrame);

        % Nur 1 Hz loggen
        if DEBUG
            if isempty(lastTickLog) || (tRel - lastTickLog) >= 1.0
                LOG('Tick: tNow=%.3f s (Frame %d)', tNow, iFrame);
                lastTickLog = tRel;
            end
        end
    end

    function onAddROI(~,~)
        % Nutzerhinweis & Cursor
        lblStatus.Text = 'ROI-Modus: Im Video klicken und ziehen, um den Bereich zu markieren. ESC bricht ab.';
        LOG('ROI-Modus aktiv.');
        oldPtr = fig.Pointer; 
        fig.Pointer = 'crosshair';
        drawnow;
    
        try
            % Rechteck zeichnen
            r = drawrectangle(axVid, ...
                'DrawingArea', [0 0 vidWH(1) vidWH(2)], ...
                'StripeColor','r', ...
                'InteractionsAllowed','all');
    
            % Falls Nutzer sofort abbricht
            if isempty(r) || ~isvalid(r)
                lblStatus.Text = 'ROI abgebrochen.';
                fig.Pointer = oldPtr; 
                return;
            end
    
            % Listener & Daten übernehmen
            el = addlistener(r, 'ROIMoved', @onRectMoved);
            rects(end+1).h = r;
            rects(end).el = el;
    
            % Tabellenzeile anlegen
            T = tbl.Data;
            pos = num2str(r.Position, '%5.0f');
            newRow = {categorical("_", roiNames), string(pos), ...
                      categorical("any", fmtOptions), "", 1.20};  % fmt, pattern, max_scale
            if strcmp(string(newRow{1}), "t_s")
                newRow{3} = categorical("time_hh:mm:ss", fmtOptions);
            elseif contains(string(newRow{1}), "v_Fzg")
                newRow{3} = categorical("integer", fmtOptions);
            end

            if isempty(T)
                T = cell2table(newRow, 'VariableNames', {'name_roi','roi','fmt','pattern','max_scale'});
            else
                T = [T; cell2table(newRow, 'VariableNames', {'name_roi','roi','fmt','pattern','max_scale'})];
            end
            T.name_roi = setcats(T.name_roi, roiNames);
            T.fmt      = setcats(T.fmt, fmtOptions);
            tbl.Data   = T;

    
            % Optisches Highlight
            highlightSelected(numel(rects));
    
            lblStatus.Text = 'ROI hinzugefügt. Du kannst die Ecken ziehen oder weitere ROIs anlegen.';
            LOG('ROI hinzugefügt: %s', pos);
        catch ME
            lblStatus.Text = 'ROI-Auswahl fehlgeschlagen.';
            LOG('ROI-Fehler: %s', ME.message);
        end
    
        % Cursor zurück
        fig.Pointer = oldPtr;

        updateRunButtonState();   % <— NEU

    end


    function onRectMoved(~,~)
        T = tbl.Data;
        for k = 1:numel(rects)
            if isvalid(rects(k).h)
                T.roi{k} = num2str(rects(k).h.Position, '%5.0f');
            end
        end
        tbl.Data = T;
    end

    function onDelROI(~,~)
        idx = tbl.Selection;
        if isempty(idx), return; end
        i = idx(1);
        if i<=numel(rects) && isvalid(rects(i).h)
            try delete(rects(i).h); catch, end
            try delete(rects(i).el); catch, end
        end
        rects(i) = [];
        T = tbl.Data; T(i,:) = []; tbl.Data = T;
        for k=1:numel(rects), if isvalid(rects(k).h), rects(k).h.Color = [0 0.4470 0.7410]; end, end
        updateRunButtonState();   % <— NEU
        LOG('ROI gelöscht: Index %d', i);
    end

    function highlightSelected(i)
        for k=1:numel(rects), if isvalid(rects(k).h), rects(k).h.Color = [0 0.4470 0.7410]; end, end
        if i<=numel(rects) && isvalid(rects(i).h), rects(i).h.Color = [1 0 0]; end
    end
    
    % ======================== Hilfsfunktionen ===============================
    
    function imageSize = getVideoFrameSize(vr)
        tKeep = safeGetCurrentTime(vr);
        I = readFrameAtTime(vr, max(0,min(vr.Duration-1e-6,0)));
        imageSize = [size(I,1), size(I,2)]; % [H W]
        safeSetCurrentTime(vr, tKeep);
    end
    
    function t = safeGetCurrentTime(vr)
        try t = vr.CurrentTime; catch, t = 0; end
    end
    
    function safeSetCurrentTime(vr, t)
        try vr.CurrentTime = max(0,min(vr.Duration-1e-6, t)); catch, end
    end
    
    function I = readFrameAtTime(vr, tsec)
        tsec = max(0, min(max(0, vr.Duration-1e-6), tsec));
        vr.CurrentTime = tsec;
        I = readFrame(vr);
    end
    
    
    function visBoundaries(ax,B)
        % einfache Boundary-Visualisierung ohne ToolBox-Abhängigkeit
        [r,c] = find(B);
        plot(ax, c, r, '.', 'MarkerSize', 1);
    end
    
    function uiwaitForButtons(fig, keys)
        % Blockiert bis eines der appdata-Keys gesetzt wurde oder Fenster zu ist
        setappdata(fig,'waitflag',true);
        set(fig,'CloseRequestFcn',@(src,evt) setappdata(fig,'waitflag',false));
        while true
            drawnow;
            if ~ishandle(fig), break; end
            if ~getappdata(fig,'waitflag'), break; end
            hit = false;
            for k=1:numel(keys)
                if ~isempty(getappdata(fig, keys{k})), hit = true; break; end
            end
            if hit, break; end
            pause(0.02);
        end
    end

    function success = startupOCR(varargin)

        success = false;

        % ======= Guards / UI State =======
        % if isOCRRunning
        %     onStopOCR(); 
        %     return
        % end

        if isPlaying, onPlayPause(); end
        stopAudio();
    
        % isOCRRunning = true;
        % ocrAbortRequested = false;
        % btnRunOCR.Text = 'Stop OCR';
        % btnRunOCR.ButtonPushedFcn = @onStopOCR;
    
        if ~allROIsNamedProperly()
            try
                Tcheck = coerceDataToTable(tbl.Data, tbl.ColumnName);
                bad = find(strcmp(string(Tcheck.name_roi), "_"));
                if ~isempty(bad)
                    try tbl.Selection = [bad(1) 1]; catch, end
                end
            catch
            end
            uialert(fig,'Bitte allen ROIs einen Namen aus der Liste zuweisen (nicht "_").', ...
                    'ROIs unbenannt','Icon','warning');
            warning("ROIs unbenannt")
            lblStatus.Text = 'ROIs unbenannt – bitte Namen setzen.';
            return
        end
    
        lblStatus.Text = 'OCR-Vorbereitung gestartet …'; LOG('OCR-Vorbereitung gestartet …');
        % pbShow(true); pbSet(0,'OCR-Vorbereitung: initialisiere …');
        lblStatus.Text = 'OCR-Vorbereitung läuft … (erneut klicken zum Stoppen)';
        drawnow;
    
        % ======= VideoReader absichern =======
        if ~isa(v,'VideoReader'), v = VideoReader(videoPath); end
    
        % ======= ROI-Tabelle =======
        TroiRaw = tbl.Data;
        Troi    = sanitizeROIData(coerceDataToTable(TroiRaw, tbl.ColumnName));
        if isempty(Troi), uialert(fig,'Bitte mindestens eine ROI anlegen.','Hinweis'); return; end
        nameNorm = strip(lower(string(Troi.name_roi)));
    
        % OCR-ROIs vs. track_minimap
        iTrk     = find(nameNorm=="track_minimap", 1);
        useTrack = ~isempty(iTrk);
        if useTrack
            isTrackROI = (nameNorm=="track_minimap");
            TroiOCR    = Troi(~isTrackROI,:);
        else
            TroiOCR    = Troi;  % ohne Track: alle ROIs sind OCR-ROIs
        end
    
        % ======= Track-Kalibrierung (trkCalSlim-Reuse) =======
        trkCal     = [];
        trkCalSlim = [];
        try
            if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'trkCalSlim')
                trkCalSlim = recordResult.ocr.trkCalSlim;
            end
        catch
            trkCalSlim = []; 
        end

        trackName = '';
    
        if useTrack
            % ROI der Minimap holen (robust)
            try
                roi = getActualTrackRoi(Troi, iTrk);
            catch
                % Fallback: Feld "roi" in Tabelle parsen
                roi = str2double(strsplit(string(Troi.roi{iTrk}), ' '));
                if numel(roi)~=4
                    uialert(fig,'Ungültige track_minimap ROI.','Track','Icon','warning'); return;
                end
            end

            % if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'noTrackCalibIfPoss')
            %     noTrackCalibIfPoss = recordResult.ocr.noTrackCalibIfPoss;
            % else
            %     choiceNoTrackCalibIfPoss = questdlg( ...
            %          sprintf('Keine erneute Kalibrierung der Strecke wenn möglich die nächsten Male?'), ...
            %         'Kalibrierung der Karte','Nicht kalibrieren','Neu kalibrieren','Nicht kalibrieren');
            %     noTrackCalibIfPoss = strcmp(choiceNoTrackCalibIfPoss,'Nicht kalibrieren');
            % end
            if noTrackCalibIfPoss
                LOG("mögl. erneute Kalibrierung der Karte nicht aktiviert.")
            else
                LOG("mögl. erneute Kalibrierung der Karte aktiviert.")
            end
    
            % Reuse-Vorschau, wenn trkCalSlim existiert und ROI gleich ist
            if ~isempty(trkCalSlim) && isfield(trkCalSlim,'roi')
                savedRoi = trkCalSlim.roi;
                if numel(savedRoi)==4 && all(abs(roi - savedRoi) < 1e-6)
                    try
                        if noTrackCalibIfPoss
                            choiceCalibration = 'Behalten';
                        else
                            choiceCalibration = showActualCalibAndChoose(roi, v, ddTrack.Value, trkCalSlim);
                        end

                        if strcmp(choiceCalibration,'Neukalibrieren')
                            trkCalSlim = []; % erzwinge Neu-Kalibrierung
                        end
                    catch
                        % Falls Vorschau fehlschlägt → kein Abbruch, einfach weiter
                    end
                end
            end
    
            % Kalibrieren (oder aus Slim rekonstruieren)
            try
                [trkCal, trkCalSlim] = runTrackCalibration(roi, v, ddTrack.Value, fig, sldStart.Value, trkCalSlim);
                trackName = ddTrack.Value;
            catch ME
                if strcmp(ME.identifier,'Track:CalibrationAborted')
                    cleanupAndReset(); 
                    return
                else
                    uialert(fig,"Track-Kalibrierung fehlgeschlagen: "+ME.message,'Track','Icon','warning');
                    cleanupAndReset();
                    return
                end
            end
        end
    
        % ======= Resume-Check =======
        ocrResume   = false;
        tStart      = sldStart.Value;
        fpsForGap   = vidFPS;
        prevOut     = [];
        if exist('nFramesOcrProgress','var')~=1 || isempty(nFramesOcrProgress), nFramesOcrProgress = 10; end

        if ocrResumeIfPossible
            LOG("Automatische Fortsetzung des OCRs wenn möglich aktiviert.")
        else
            LOG("Automatische Fortsetzung des OCRs wenn möglich nicht aktiviert.")
        end
    
        if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'table') && istable(recordResult.ocr.table)
            prevOut = recordResult.ocr.table;
            % fps aus früherem Lauf bevorzugen
            try
                if isfield(recordResult.ocr,'params') && isfield(recordResult.ocr.params,'fps')
                    fpsForGap = double(recordResult.ocr.params.fps);
                end
            catch 
                fpsForGap = vidFPS; 
            end
    
            deltaTime = 1/max(1, fpsForGap);
    
            % Resume-Heuristik:
            % 1) klassisch: erste 0 in time_s (außer Index 1)
            nextTime = NaN;
            try
                idx0 = find(prevOut.time_s == 0);
                idx0 = idx0(idx0~=1);
                if ~isempty(idx0)
                    lastTime = prevOut.time_s(idx0(1)-1);
                    if isfinite(lastTime)
                        nextTime = lastTime + deltaTime;
                    end
                end
            catch
                nextTime = NaN;
            end
            % 2) sonst: am Ende noch Lücke zur GUI-Ende?
            if ~isfinite(nextTime) || nextTime<=0
                try
                    lastTimeFilled = max(prevOut.time_s(prevOut.time_s>0));
                    if isfinite(lastTimeFilled)
                        cand = lastTimeFilled + deltaTime;
                        if cand < sldEnd.Value-1e-6
                            nextTime = cand;
                        end
                    end
                catch
                    % ignore
                end
            end
   
            if isfinite(nextTime) && (nextTime < sldEnd.Value)
                
                if ocrResumeIfPossible
                    ocrResume = true;
                else
                    choiceResumeOCR = questdlg( ...
                        [sprintf('Bisheriger OCR-Fortschritt bis t = %.2f s.', max(prevOut.time_s)) newline ...
                         sprintf('Ab t = %.2f s fortsetzen (und nächstes Mal auch)?', nextTime)], ...
                        'OCR fortsetzen','Fortsetzen','Neu anfangen','Fortsetzen');
                    ocrResume = strcmp(choiceResumeOCR,'Fortsetzen');
                end
                
                if ocrResume, tStart = nextTime; end
            else

            end
        end

        if analyzeRPMAfterOCR
            LOG("Automatische RPM Auswertung nach OCR-Abschluss aktiviert.")
        else
            LOG("Automatische RPM Auswertung nach OCR-Abschluss nicht aktiviert.")
        end

        %% Save to .mat-File       
        if isfield(recordResult, "ocr")
            ocrResult = recordResult.ocr;
        else
            ocrResult = struct();
        end

        ocrResult.created = datetime('now');
        % KEINE ocr.video/audio mehr – Pfade liegen in recordResult.metadata.*
        ocrResult.params  = struct('start_s', sldStart.Value, ...
                                   'end_s',   sldEnd.Value, ...
                                   'resume_from_s', tStart, ...
                                   'audio_offset_s', sldOff.Value, ...
                                   'fps', vidFPS, ...
                                   'duration_s', vidDuration, ...
                                   'video_size_wh', vidWH);
        ocrResult.roi_table     = Troi;
        ocrResult.roi_table_raw = TroiRaw;
        ocrResult.roi_catalog   = struct('roiNames',{roiNames}, 'fmtOptions',{fmtOptions});
        ocrResult.trkCalSlim    = trkCalSlim;

        if useTrack
            ocrResult.track = slimTrack(trkCal); 
            ocrResult.track.trackName = trackName;
        end

        % Overwrite
        recordResult.ocr = ocrResult;
        save(filePath,'recordResult','-v7.3');

        try populateOCRDropdowns(); catch, end

        % uialert(fig, sprintf('%s OCR-Vorbereitung abgeschlossen.\n\nGespeichert in: %s\nVariable: recordResult.ocr', ...
        %     char(10003), filePath), ...
        %     'Fertig','Icon','success');
        lblStatus.Text = sprintf('%s OCR-Vorbereitung abgeschlossen – MAT aktualisiert: %s', char(10003), filePath);

        %% Append to global param
        ocrInfos = struct();
        ocrInfos.ocrResume = ocrResume;
        ocrInfos.tStart = tStart;
        ocrInfos.TroiOCR = TroiOCR;
        ocrInfos.prevOut = prevOut;
        ocrInfos.trkCal = trkCal;
        ocrInfos.trkCalSlim = trkCalSlim;
        ocrInfos.TroiRaw = TroiRaw;
        ocrInfos.useTrack = useTrack;
        ocrInfos.Troi = Troi;
        ocrInfos.fpsForGap = fpsForGap;
        ocrInfos.trackName = trackName;

        success = true;

    end

    function onRunOCR(varargin)
        
         % Aufrufvarianten:
        %   onRunOCR()           % CLI / Auto
        %   onRunOCR(src, evt)   % Button-Callback

        % ======= Guards / UI State =======

        if ~startupOCR()
            
            if cliRunOCR
                LOG('CLI: OCR abgeschlossen – GUI wird geschlossen.');
                try
                    close(fig);
                catch
                end
            end

            return
            
        end

        if isOCRRunning
            onStopOCR(); 
            return
        end

        % if isPlaying, onPlayPause(); end
        % stopAudio();
    
        isOCRRunning = true;
        ocrAbortRequested = false;
        btnRunOCR.Text = 'Stop OCR';
        btnRunOCR.ButtonPushedFcn = @onStopOCR;

        % Load param
        ocrResume = ocrInfos.ocrResume;
        tStart = ocrInfos.tStart;
        TroiOCR = ocrInfos.TroiOCR;
        prevOut = ocrInfos.prevOut;
        trkCal = ocrInfos.trkCal;
        trkCalSlim = ocrInfos.trkCalSlim;
        TroiRaw = ocrInfos.TroiRaw;
        useTrack = ocrInfos.useTrack;
        Troi = ocrInfos.Troi;
        fpsForGap = ocrInfos.fpsForGap;
        trackName = ocrInfos.trackName;

        lblStatus.Text = 'OCR gestartet …'; LOG('OCR gestartet …');
        pbShow(true); pbSet(0,'OCR: initialisiere …');
        lblStatus.Text = 'OCR läuft … (erneut klicken zum Stoppen)';
        drawnow;

        % ======= Vorbereiten & Prealloc =======
        v.CurrentTime = tStart;
        nFrames = max(0, floor((sldEnd.Value - tStart) * vidFPS));
        if nFrames == 0
            uialert(fig,'Nichts zu tun im gewählten Zeitfenster.','Hinweis','Icon','warning');
            cleanupAndReset(); 
            
            if cliRunOCR
                LOG('CLI: OCR abgeschlossen – GUI wird geschlossen.');
                close(fig);
            end

            return
        end
    
        pbSet(0, sprintf('OCR: 0/%d', nFrames));
    
        % Ergebnis-Tabelle der neuen Portion
        outNew = table('Size',[nFrames, 2], ...
                       'VariableTypes',{'double','double'}, ...
                       'VariableNames',{'time_s','frame_idx'});
    
        % Spalten für OCR-ROIs (Strings)
        for r = 1:height(TroiOCR)
            colName = safeVarName(TroiOCR.name_roi(r));
            outNew.(colName) = strings(nFrames,1);
        end
        % Track-Spalten
        if useTrack
            outNew.track_pct  = nan(nFrames,1);
            outNew.track_s_m  = nan(nFrames,1);
            outNew.track_xy_x = nan(nFrames,1);
            outNew.track_xy_y = nan(nFrames,1);
        end
    
        LOG('OCR-Start: Frames=%d, ROIs=%d, tStart=%.3f', nFrames, height(Troi), tStart);
        wasAborted = false;
    
        trkState = struct();

        % Live-Tabelle initialisieren
        liveData = table(Troi.name_roi, repmat("", height(Troi), 1), ...
                         'VariableNames', {'name_roi','last_text'});
        liveData.name_roi = setcats(liveData.name_roi, roiNames);
        tblLive.Data = liveData;

        % --- Mapping von OCR-ROIs (TroiOCR) -> liveData-Zeilen ---
        nameLive = string(liveData.name_roi);
        nameOCR  = string(TroiOCR.name_roi);
        [~, mapOCR2Live] = ismember(nameOCR, nameLive);  % 0 wenn nicht gefunden
        
        % --- Zeile der track_minimap in liveData finden (falls vorhanden) ---
        iTrackLive = find(strip(lower(nameLive)) == "track_minimap", 1);
        if isempty(iTrackLive)
            iTrackLive = [];  % explizit leer, damit ~isempty() unten funktioniert
        end

        % ======= Hauptschleife =======
        for i=1:nFrames
            if ocrAbortRequested, wasAborted = true; break; end
            try
                fr = readFrame(v);
            catch
                break
            end
    
            tNow = tStart + (i-1)/vidFPS;
            outNew.time_s(i)   = tNow;
            outNew.frame_idx(i)= i;
    
            % ---- Track-Update ----
            if useTrack
                try
                    miniNow = imcrop(fr, trkCal.roi);
                catch
                    miniNow = [];
                end
                if ~isempty(miniNow)
                    [uv, ok, trkState] = detectMarkerMotionColor_(miniNow, trkCal.mask, trkState, trkCal.marker);
                    if ok
                        XY = trkCal.warp.applyFun(uv(:).');
                        [pct, s_q, proj_xy] = progressOnPolylineWithProj_(trkCal.centerline, XY, trkCal.s_total, trkCal.sCum);
                        outNew.track_pct(i)  = 100*pct;
                        outNew.track_s_m(i)  = s_q;
                        outNew.track_xy_x(i) = XY(1);
                        outNew.track_xy_y(i) = XY(2);
                        if ~isempty(iTrackLive) && iTrackLive <= height(liveData)
                            liveData.last_text(iTrackLive) = sprintf('%.1f %%  |  s=%d m', 100*pct, round(s_q)); 
                        end
                        if mod(i,nFramesOcrProgress)==0
                            updateTrackDetailsIfOpen(miniNow, trkCal.mask, uv, trkCal.centerline, XY, proj_xy, tNow, 100*pct, trkCal.ptsRef, trkCal.ptsMini, trkCal.warp);
                        end
                    else
                        if ~isempty(iTrackLive) && iTrackLive <= height(liveData)
                            liveData.last_text(iTrackLive) = "—"; 
                        end
                    end
                end
            end
    
            % ---- Live-Preview ----
            if mod(i,nFramesOcrProgress)==0
                try
                    hImg.CData = fr; 
                catch
                end
                
                if ~isempty(hSync) && isgraphics(hSync)
                    hSync.Value = tNow + sldOff.Value; 
                end

                updateNowLabels(tNow, i);
                drawnow limitrate;
            end
    
            % ---- OCR je ROI ----
            for r = 1:height(TroiOCR)
                rect = str2double(strsplit(TroiOCR.roi{r}, ' '));
                fmt  = TroiOCR.fmt(r);
                pat  = TroiOCR.pattern(r);
                maxSc = double(TroiOCR.max_scale(r)); if ~isfinite(maxSc) || maxSc < 1.0, maxSc = 1.0; end
    
                charset = getCharSetForFormat(fmt);
    
                found = false; bestVal = "";
                for sc = 1.00 : 0.05 : (maxSc + 1e-9)
                    rectExp = expandRect(rect, sc, vidWH);
                    try
                        frCrop = imcrop(fr, rectExp);
                    catch
                        frCrop = fr;
                    end
    
                    frUp = imresize(frCrop, 2.0, 'bilinear');
                    gray = frUp; if size(gray,3)==3, gray = rgb2gray(gray); end
                    gray = imadjust(gray);
                    bw   = imbinarize(gray, 'adaptive', 'Sensitivity', 0.45, 'ForegroundPolarity', 'dark');
    
                    if ~isempty(charset)
                        txtA = ocr(frUp, 'CharacterSet', charset, 'TextLayout','Block');
                        txtB = ocr(bw,   'CharacterSet', charset, 'TextLayout','Block');
                    else
                        txtA = ocr(frUp, 'TextLayout','Block');
                        txtB = ocr(bw,   'TextLayout','Block');
                    end
    
                    rawA = strjoin(txtA.Words); rawB = strjoin(txtB.Words);
                    confA = mean(getfieldOr(txtA,'WordConfidences',[]),'omitnan'); if isnan(confA), confA=0; end
                    confB = mean(getfieldOr(txtB,'WordConfidences',[]),'omitnan'); if isnan(confB), confB=0; end
    
                    scoreA = double(strlength(rawA)) + 5*double(confA);
                    scoreB = double(strlength(rawB)) + 5*double(confB);
                    raw    = iff(scoreB>scoreA, rawB, rawA);
    
                    [ok, val] = validateFormatted(raw, fmt, pat);
                    if ok
                        bestVal = val; 
                        found = true; 
                        break; 
                    end
                end
    
                colName = safeVarName(TroiOCR.name_roi(r));
                if found
                    outNew.(colName)(i) = bestVal;
                    rowLive = mapOCR2Live(r);
                    if rowLive > 0 && rowLive <= height(liveData)
                        liveData.last_text(rowLive) = string(bestVal);
                    end
                else
                    outNew.(colName)(i) = "";
                    rowLive = mapOCR2Live(r);
                    if rowLive > 0 && rowLive <= height(liveData)
                        liveData.last_text(rowLive) = "⛔";
                    end
                end
                tblLive.Data = liveData;
            end
    
            if mod(i,nFramesOcrProgress)==0
                pbSet(i/max(1,nFrames), sprintf('OCR: %d/%d', i, nFrames));
            end
    
            if DEBUG && ~mod(i, max(1,round(nFrames/10)))
                LOG('OCR Fortschritt: %d/%d', i, nFrames);
            end
        end
    
        
        % ======= Nach OCR: Zeit interpretieren & Auswertung =======
        outMerged = outNew;
        if ocrResume && ~isempty(prevOut)
            outMerged = mergeOutTables(prevOut, outNew, tStart, fpsForGap);
        end
           
        % ======= Speichern =======
        ocrExists = isfield(recordResult,'ocr') && isfield(recordResult.ocr,'table');
        overwriteAllowed = true; % beim Fortsetzen überschreiben wir sinnvoll
    
        ocrResult = struct();
        ocrResult.created = datetime('now');
        % KEINE ocr.video/audio mehr – Pfade liegen in recordResult.metadata.*
        ocrResult.params  = struct('start_s', sldStart.Value, ...
                                   'end_s',   sldEnd.Value, ...
                                   'resume_from_s', tStart, ...
                                   'audio_offset_s', sldOff.Value, ...
                                   'fps', vidFPS, ...
                                   'duration_s', vidDuration, ...
                                   'video_size_wh', vidWH);
        ocrResult.roi_table     = Troi;
        ocrResult.roi_table_raw = TroiRaw;
        ocrResult.roi_catalog   = struct('roiNames',{roiNames}, 'fmtOptions',{fmtOptions});
        ocrResult.table         = outMerged;
        ocrResult.trkCalSlim    = trkCalSlim;

        if useTrack
            ocrResult.track = slimTrack(trkCal); 
            ocrResult.track.trackName = trackName;
        end

    
        % Typ-Normalisierung/Propagation (wie gehabt, unverändert sinnvoll)
        try
            % Erstelle ein Map
            fmtMap = containers.Map('KeyType','char','ValueType','char');
            
            % Kopiere ROI Table
            rt = Troi;

            % Fülle Map mit fmt aus ROI Table
            if ismember('name_roi', rt.Properties.VariableNames) && ismember('fmt', rt.Properties.VariableNames)
                for ii = 1:height(rt)
                    key = char(string(rt.name_roi(ii)));
                    val = string(rt.fmt(ii));
                    
                    if contains(val,"int")
                        fmtMap(key) = "int";
                    else
                        fmtMap(key) = val;
                    end
                end
            end

            % Kopiere die Tabelle
            tblOCR = outMerged;

            % Iteration über alle Parameter vom tblOCR
            for varName = tblOCR.Properties.VariableNames

                % Hole name des Parameters
                name = char(varName); 
                
                % Platzhalter
                want = '';

                % Bei t_s: Sonderbehandlung
                if strcmp(name,'t_s')
                    want = fmtMap(name);

                    if strcmp(want,'any')
                        % Nichts machen
                    elseif contains(want, 'int')
                        tblOCR.t_s = toDoubleVec(tblOCR.t_s);
                    elseif contains(want, 'time_')
                        timeFmt = replace(want, "time_", "");
                        tblOCR.t_s = parse_seconds(tblOCR.t_s, timeFmt);
                    end
                    
                    continue; 
                end
                
                % Hole die entsprechende Spalte
                col = tblOCR.(name);

                % Konvertiere je nach fmt
                if isKey(fmtMap,name)
                    want = fmtMap(name);
                end

                if isempty(want)
                    test = toDoubleVec(col);
                    if ~isempty(test)
                        if all(~isnan(test)&isfinite(test)&abs(test-round(test))<1e-6)
                            want='int'; 
                        else
                            want='float'; 
                        end
                    end
                end

                num = toDoubleVec(col);

                if strcmp(want,'int')
                    num = round(num);
                end

                if ~isempty(num)
                    tblOCR.(name) = num; 
                end
            end

        catch ME
            warning(ME.identifier,'Type-Normalisierung/Propagation fehlgeschlagen: %s', ME.message);
        end

        % wenn t_s verfügbar ist
        if ismember('t_s', tblOCR.Properties.VariableNames)

            % Lösche alle NaN-Values
            idxNan = isnan(tblOCR.t_s);
            tblOCR = tblOCR(~idxNan, :);

            % Ensure unique values
            [~, ia, ~] = unique(tblOCR.t_s, "last"); % get last occurences
            tblOCR = tblOCR(ia, :);
        end

        % Unabhängig vom t_s: lösche alle Zeilen wo time_s 0 ist
        idx0 = tblOCR.time_s == 0;
        tblOCR = tblOCR(~idx0, :);

        if ismember('v_Fzg_kmph', tblOCR.Properties.VariableNames)
            % Lösche alle NaN-Values
            idxNan = isnan(tblOCR.v_Fzg_kmph);
            tblOCR = tblOCR(~idxNan, :);
        end

        if ismember('v_Fzg_mph', tblOCR.Properties.VariableNames)
            % Lösche alle NaN-Values
            idxNan = isnan(tblOCR.v_Fzg_mph);
            tblOCR = tblOCR(~idxNan, :);
        end

        % in Processed reintun
        ocrResult.cleaned = tblOCR;

        ocrResult.cleaned_info = struct( ...
                'track', ddTrack.Value ...
                );
    
        lblStatus.Text = 'Fertig.';
    
        if ocrExists && ~overwriteAllowed
            uialert(fig,'Vorhandenes OCR-Ergebnis wurde beibehalten – neues Ergebnis NICHT gespeichert.','Kein Speichern','Icon','warning');
            lblStatus.Text = 'Ergebnis NICHT gespeichert (Behalten gewählt).';
        else
            recordResult.ocr = ocrResult;
            save(filePath,'recordResult','-v7.3');

            try populateOCRDropdowns(); catch, end

            uialert(fig, sprintf('%s OCR abgeschlossen.\n\nGespeichert in: %s\nVariable: recordResult.ocr', char(10003), filePath), ...
                    'Fertig','Icon','success');
            lblStatus.Text = sprintf('%s OCR abgeschlossen – MAT aktualisiert: %s', char(10003), filePath);
        end
    
        % ======= Cleanup / Reset =======
        stopAudio();
        isPlaying    = false;
        btnPlay.Text = 'Play';
        tResumeAbs   = sldStart.Value;
        tBaseAbs     = sldStart.Value;
        if wasAborted
            lblStatus.Text = 'OCR abgebrochen. (Keine Speicherung/Exports durchgeführt.)';
        else
            lblStatus.Text = 'Fertig.';
        end
        pbShow(false);
        isOCRRunning = false;
        ocrAbortRequested = false;
        resetRunButton();
        restoreAudioToInitial();
        sldEnd.Value = max(sldEnd.Value, sldStart.Value + minWindowDt());
        onEndChanged(sldEnd.Value);
    
        % Versuche RPM auszuwerten
        if analyzeRPMAfterOCR
            try
                onRunRPM2();
            catch
            end
        end

        if wasAborted
            restoreAudioToInitial();
        end

        % ===============================================================
        % CLI-Modus: Wenn OCR erfolgreich durchgelaufen ist → Fenster schließen
        % ===============================================================
        if cliRunOCR
            LOG('CLI: OCR abgeschlossen – GUI wird geschlossen.');
            close(fig);
        end

        if wasAborted
            return
        end

        % ======= NESTED HELPERS =======
    
        function secs = parse_seconds(t, fmts)
        %PARSE_SECONDS Parst Zeitstrings mit benutzerdefinierten Formaten in Sekunden (double).
        % t    : string|char|string-Array|cellstr
        % fmts : string|char|string-Array|cellstr  (ein oder mehrere InputFormate für duration)
        %
        % Beispiel:
        %   parse_seconds("01:02:03.450", "hh:mm:ss.SSS")         % 3723.450
        %   parse_seconds(["02:05","00:59"], ["mm:ss","hh:mm:ss"])% probiert mm:ss, dann hh:mm:ss
        
            if iscell(t);   t = string(t); end
            if ischar(t);   t = string(t); end
            if ~isstring(t); error('t muss string/char/cellstr/string-Array sein.'); end
        
            if iscell(fmts); fmts = string(fmts); end
            if ischar(fmts); fmts = string(fmts); end
            if ~isstring(fmts); error('fmts muss string/char/cellstr/string-Array sein.'); end


            buchstaben = ["h", "m", "s", "S"];
            fmtsEnd = [];
            for buchstabe = buchstaben
                if contains(fmts, buchstabe)
                    if strcmp(buchstabe, "S")
                        newStr = strjoin(repelem(buchstabe, 1, 6), ""); % Erstelle "SSSSSS"
                    else
                        newStr = strjoin(repelem(buchstabe, 1, 2), ""); % Erstelle "hh", "mm", "ss"
                    end

                    fmtsEnd = [fmtsEnd, newStr];

                    if length(fmtsEnd) > 1
                        if strcmp(buchstabe, "S")
                            fmtsEnd = join(fmtsEnd, ".");
                        else
                            fmtsEnd = join(fmtsEnd, ":");
                        end
                    end
                end
            end
        
            secs = NaN(size(t));
            for idx = 1:numel(t)
                x = t(idx);
                if x == "" || ismissing(x)
                    secs(idx) = NaN; 
                    continue;
                end
                parsed = false;
                for f = fmtsEnd(:).'
                    try
                        d = duration(x, 'InputFormat', f);
                        secs(idx) = seconds(d);
                        parsed = true;
                        break;
                    catch ME
                        if strcmp(ME.identifier, 'MATLAB:duration:UnrecognizedInputFormat')
                            warning(ME.identifier,'Falsches Format: %s', ME.message);
                        else
                            % Data nicht parseable, z.B. "000a5Y0)"
                            % -> nichts tun, einfach NaN lassen
                        end
                    end
                end
                if ~parsed
                    % bleibt NaN
                end
            end
        end


        function t = getfieldOr(s, fn, def)
            try t = s.(fn); catch, t = def; end
        end
    
        function y = iff(cond,a,b)
            if cond, y=a; else, y=b; end
        end
    
        
    
        function outAll = mergeOutTables(prev, addNew, tStartLocal, fpsPrev)
            % prev: alte Tabelle (ggf. mit trailing zeros)
            % addNew: neue Portion ab tStartLocal
            % -> schneidet prev auf < tStartLocal und hängt addNew an
            if ~ismember('time_s', prev.Properties.VariableNames), outAll = addNew; return; end
            filled = prev.time_s > 0 & isfinite(prev.time_s);
            if ~any(filled), outAll = addNew; return; end
            delta = 1/max(1,fpsPrev);
            keepPrev = filled & (prev.time_s < (tStartLocal - 0.5*delta));
            prevTrim = prev(keepPrev, :);
    
            % Spalten harmonisieren
            [prevTrim2, addNew2] = harmonizeTables(prevTrim, addNew);
            outAll = [prevTrim2; addNew2];
        end
    
        function [A,B] = harmonizeTables(A,B)
            % fügt fehlende Spalten hinzu (string→"", numeric→NaN)
            allNames = union(A.Properties.VariableNames, B.Properties.VariableNames, 'stable');
            for k = 1:numel(allNames)
                vn = allNames{k};
                if ~ismember(vn, A.Properties.VariableNames)
                    Bcol = B.(vn);
                    if isstring(Bcol) || (iscell(Bcol) && (isempty(Bcol) || ischar(Bcol{1})))
                        A.(vn) = strings(height(A),1);
                    else
                        A.(vn) = nan(height(A),1);
                    end
                end
                if ~ismember(vn, B.Properties.VariableNames)
                    Acol = A.(vn);
                    if isstring(Acol) || (iscell(Acol) && (isempty(Acol) || ischar(Acol{1})))
                        B.(vn) = strings(height(B),1);
                    else
                        B.(vn) = nan(height(B),1);
                    end
                end
            end
            % gleiche Reihenfolge
            A = A(:, allNames);
            B = B(:, allNames);
        end
    end

    function cleanupAndReset()
        pbShow(false);
        isOCRRunning = false;
        ocrAbortRequested = false;
        resetRunButton();
        restoreAudioToInitial();
    end


    % ==== Hilfsfunktionen (lokal für Drop-in 1) ====
    function v = toDoubleVec(col)
        % Robust parser -> double column vector, NaN for non-parsable.
        if isempty(col)
            v = [];
            return;
        end
    
        % --- Fast paths ---
        if isnumeric(col) || islogical(col)
            v = double(col(:));
            return;
        end
        if isdatetime(col)
            % Sekunden seit 1970 (oder wähle datenum/posixtime – hier posixtime)
            try
                v = posixtime(col(:));
                v = double(v);
                return;
            catch
            end
        end
        if isduration(col)
            try
                v = seconds(col(:));
                v = double(v);
                return;
            catch
            end
        end
    
        % --- Normalize container to cellstr-ish for parsing ---
        if isstring(col)
            c = cellstr(col);
        elseif ischar(col)
            c = {col};
        elseif iscell(col)
            c = col(:);
        elseif iscategorical(col)
            c = cellstr(string(col));
        else
            % Last resort: try double(), else string() -> parse
            try
                v = double(col(:));
                return;
            catch
                c = cellstr(string(col(:)));
            end
        end
    
        % Ensure cell column
        c = c(:);
    
        % Parse each cell robustly
        n = numel(c);
        v = nan(n,1);
        for i = 1:n
            x = c{i};
            if isempty(x)
                v(i) = NaN;
            elseif isnumeric(x) || islogical(x)
                v(i) = double(x);
            else
                v(i) = parse_numeric_scalar(x);
            end
        end
    end
    
    function d = parse_numeric_scalar(s)
        % Accept char/string mixed content, locale variants, signs, exponents.
        if isstring(s), s = char(s); end
        if ~ischar(s), d = NaN; return; end
    
        % Trim & unify spaces
        s = strtrim(s);
        if isempty(s), d = NaN; return; end
    
        % Normalize unicode minus and spaces
        s = strrep(s, char(8722), '-'); % '−' -> '-'
        s = strrep(s, char(160),  ' '); % NBSP
        s = strrep(s, char(8239), ' '); % NNBSP
        s = regexprep(s, '\s+', '');   % alle Whitespaces raus (z. B. 1 234,56)
    
        % Wenn die Zeichenkette klar „verschmutzt“ ist (Units etc.), extrahiere
        % das erste Zahlen-Token inkl. Dezimal/E-Teil:
        token = regexp(s, '[-+]?\d{1,3}([.,\'']?\d{3})*([.,]\d+)?([eE][-+]?\d+)?|[-+]?\d+([.,]\d+)?([eE][-+]?\d+)?', 'match', 'once');
        if isempty(token)
            d = NaN; 
            return;
        end
    
        % Locale-Heuristik:
        % - Falls Komma UND Punkt vorkommen:
        %     letzter Trenner entscheidet über Dezimal
        % - Ansonsten: einzelnes Komma -> Dezimal; einzelner Punkt -> Dezimal
        t = token;
    
        hasDot   = contains(t, '.');
        hasComma = contains(t, ',');
    
        if hasDot && hasComma
            % Positionen prüfen
            lastDot   = find(t=='.', 1, 'last');
            lastComma = find(t==',', 1, 'last');
            if ~isempty(lastComma) && ~isempty(lastDot) && lastComma > lastDot
                % Dezimal = Komma => Punkte sind Tausender
                t = erase(t, '.');
                t = strrep(t, ',', '.');
            else
                % Dezimal = Punkt => Kommata sind Tausender
                t = erase(t, ',');
            end
        elseif hasComma && ~hasDot
            % Nur Komma => Dezimal
            t = strrep(t, ',', '.');
        else
            % Nur Punkt ODER keines -> okay; außerdem Apostroph als Tausender weg
            t = strrep(t, '''', '');
        end
    
        % Finale Konvertierung
        d = str2double(t);
        if isnan(d)
            % Zweiter Versuch: entferne verbleibende Nicht-Ziffern außer .+-eE
            t2 = regexprep(t, '[^0-9\.\+\-eE]', '');
            d  = str2double(t2);
            % Wenn immer noch NaN -> so lassen
        end
    end

    
    % function x = parseNumStr(s)
    %     if isempty(s), x = NaN; return; end
    %     s = char(s);
    %     s = regexprep(s, '[\s\u00A0\u2000-\u200A\u202F]', '');
    %     s = regexprep(s, '[’''`]', '');
    %     hasDot = contains(s,'.'); hasCom = contains(s,',');
    %     if hasDot && hasCom
    %         lastDot = find(s=='.',1,'last'); lastCom = find(s==',',1,'last');
    %         if ~isempty(lastCom) && (isempty(lastDot) || lastCom>lastDot)
    %             s = strrep(s,'.',''); s = strrep(s,',','.');
    %         else
    %             s = strrep(s,',','');
    %         end
    %     elseif hasCom && ~hasDot
    %         s = strrep(s,',','.');
    %     else
    %         s = strrep(s,',','');
    %     end
    %     s = regexprep(s,'[^0-9\+\-\.eE]','');
    %     x = str2double(s); if isempty(x) || isnan(x), x = NaN; end
    % end


    function startOrRestartAudioAt(tVideoAbs)
        if isempty(y) || isempty(fs) || ~isnumeric(tVideoAbs), return; end
        audStart = max(0, min(tVideoAbs + sldOff.Value, numel(y)/fs - 1e-3));
        s0 = max(1, floor(audStart*fs)+1);
        try
            stopAudio();                              % <— NEU: vorher alles sauber schließen
            ap = audioplayer(y(s0:end), fs);
            play(ap);
            LOG('Audio (re)start @ %.3fs (Offset=%.2fs, Sample=%d)', audStart, sldOff.Value, s0);
        catch ME
            LOG('Audio restart Fehler: %s', ME.message);
        end
    end




    function R2 = expandRect(R, scale, frameWH)
        % R=[x y w h], scale>=1; clip an Frame
        if numel(R)~=4, R2 = R; return; end
        x=R(1); y=R(2); w=R(3); h=R(4);
        cx = x + w/2; cy = y + h/2;
        w2 = w*scale; h2 = h*scale;
        x2 = max(1, round(cx - w2/2));
        y2 = max(1, round(cy - h2/2));
        x2 = min(x2, frameWH(1)-1);
        y2 = min(y2, frameWH(2)-1);
        w2 = min(round(w2), frameWH(1)-x2);
        h2 = min(round(h2), frameWH(2)-y2);
        R2 = [x2 y2 w2 h2];
    end
    
    function s = cleanOcr(s)
        % häufige OCR-Verwechslungen korrigieren & vereinheitlichen
        s = string(s);
        s = regexprep(s,'\s+','');   % Leerzeichen raus
        s = strrep(s,',','.');       % Komma -> Punkt
        s = strrep(s,'O','0');       % O -> 0
        s = strrep(s,'o','0');
        s = strrep(s,'I','1');       % I -> 1
        s = strrep(s,'l','1');       % l -> 1
        s = strrep(s,'S','5');       % S -> 5 (vorsichtig, aber hilfreich)
    end
    
    function cs = getCharSetForFormat(fmt)
        fmtStr = string(fmt);
        if isempty(fmtStr) || fmtStr=="<undefined>", fmtStr = "any"; end
        
        if contains(fmtStr, 'time_')
            cs = '0123456789:.,';
        else
            switch fmtStr
                case "integer"
                    cs = '+-0123456789';
                case "float"
                    cs = '+-0123456789.,';
                case "alnum"
                    cs = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
                otherwise
                    cs = '';
            end
        end
    end

    
    function [ok, out] = validateFormatted(textIn, fmt, pattern)
        s = cleanOcr(textIn);
        fmtStr = string(fmt);
        if isempty(fmtStr) || fmtStr=="<undefined>", fmtStr = "any"; end
    
        if contains(fmtStr, 'time_')
            tempFmtStr = replace(fmtStr, "time_", "");

            % temp_s = s;
            s = replace(strtrim(s),  {',', '.', ':'}, ' ');

            buchstaben = ["h", "m", "s", "S"];
            % idx_buchstaben_start = 1;
            % idx_buchstaben_end = 1;
            valStr = [];            

            for i = 1:length(buchstaben)
                buchstabe = buchstaben(i);
                tempCount = count(tempFmtStr, buchstabe);
                if tempCount > 0
                    valStr = [valStr, "\d{" + num2str(tempCount, "%.0f") + "}"];
                end
   
            end

            valStr = strjoin(valStr, " ");
            valStr = ["^", valStr, "$"];
            valStr = strjoin(valStr, "");

            ok = ~isempty(regexp(s, valStr,'once'));

            % wenn OK -> ändere den Format von s sodass es fmt entspricht
            if ok
                s_new = [];
                for i = 1:length(buchstaben)
                    buchstabe = buchstaben(i);
                    idx = strfind(tempFmtStr, buchstabe);
                    if ~isempty(idx)
                        sliced_str = extractBetween(s, idx(1), idx(end));
                        s_new = [s_new, sliced_str];
                        if buchstabe == "S"
                            s_new = strjoin(s_new, ".");
                        else
                            s_new = strjoin(s_new, ":");
                        end
                    end
                end
                out = s_new;
            else
                out = "";
            end
        else
            switch fmtStr
                case "any"
                    ok = true;  out = s;
        
                case "integer"
                    ok = ~isempty(regexp(s, '^[\+\-]?\d+$','once'));
                    out = s;
        
                case "int_1"
                    ok = ~isempty(regexp(s, '^[\+\-]?\d{1}$','once'));
                    out = s;
                
                case "int_2"
                    ok = ~isempty(regexp(s, '^[\+\-]?\d{2}$','once'));
                    out = s;

                case "int_3"
                    ok = ~isempty(regexp(s, '^[\+\-]?\d{3}$','once'));
                    out = s;

                case "int_4"
                    ok = ~isempty(regexp(s, '^[\+\-]?\d{4}$','once'));
                    out = s;

                case "int_min2_max3"
                    ok = ~isempty(regexp(s, '^[\+\-]?\d{2,3}$','once'));
                    out = s;

                case "int_min3_max4"
                    ok = ~isempty(regexp(s, '^[\+\-]?\d{3,4}$','once'));
                    out = s;

                case "float"
                    ok = ~isempty(regexp(s, '^[\+\-]?\d+(\.\d+)?$','once'));
                    out = s;
        
                case "alnum" % alphanumerisch -> Buchstabe und Zahlen, keine Sonderzeichen
                    ok = ~isempty(regexp(s, '^[A-Za-z0-9]+$','once'));
                    out = s;
        
                case "custom"
                    patStr = string(pattern);
                    if strlength(patStr) > 0
                        ok = ~isempty(regexp(s, patStr, 'once'));
                    else
                        ok = true;
                    end
                    out = s;
        
                otherwise
                    ok = true; out = s;
            end

        end
    end


    function onTblEdited(src, evt)
        % 1) Immer erst in table konvertieren
        T = coerceDataToTable(src.Data, tbl.ColumnName);
    
        % 2) Spalteninfo robust ziehen
        row    = evt.Indices(1);
        colIdx = evt.Indices(2);
        varName = tbl.ColumnName{colIdx};  % nicht T.Properties nutzen
    
        % 3) Rückwärtskompatibilität (scale -> max_scale)
        if any(strcmp(T.Properties.VariableNames,'scale')) && ~any(strcmp(T.Properties.VariableNames,'max_scale'))
            T.max_scale = T.scale;
        end
    
        % 4) Edit anwenden
        switch varName
            case {'max_scale','scale'}
                newScale = evt.NewData;
                if iscell(newScale), newScale = newScale{1}; end
                if isstring(newScale) || ischar(newScale), newScale = str2double(string(newScale)); end
                if ~isfinite(newScale) || newScale < 1.0, newScale = 1.0; end
                T.max_scale(row) = newScale;   % immer in max_scale schreiben

            case 'fmt'
                f = string(T.fmt);
                f(f=="" | f=="<undefined>") = "any";
                T.fmt = categorical(f, fmtOptions);
    
            case 'pattern'
                T.pattern(row) = string(T.pattern(row));
    
            case 'name_roi'
                % nichts, wird unten normiert
            case 'roi'
                % nichts, bleibt string
        end
    
        % 5) Typen/Categories fixieren
        T.name_roi = setcats(categorical(string(T.name_roi)), roiNames);
        T.fmt      = setcats(categorical(string(T.fmt)),      fmtOptions);
        T.pattern  = string(T.pattern);
        if ~ismember('max_scale', T.Properties.VariableNames)
            T.max_scale = ones(height(T),1);
        end
        if ~isnumeric(T.max_scale)
            T.max_scale = str2double(string(T.max_scale));
        end
        T.max_scale(~isfinite(T.max_scale) | T.max_scale < 1.0) = 1.0;
    
        % 6) Zurück in die Tabelle
        src.Data = T;

        % Manche Releases verwandeln Data sofort wieder in cell -> zurückkonvertieren
        src.Data = coerceDataToTable(src.Data, tbl.ColumnName);

        updateRunButtonState();   % <— NEU
    end

    function Tfix = sanitizeROIData(Tin)
        Tfix = coerceDataToTable(Tin, tbl.ColumnName);  % <-- stellt sicher, dass es eine table ist
        % name_roi/fmt als categorical
        Tfix.name_roi = setcats(categorical(string(Tfix.name_roi)), roiNames);
        Tfix.fmt      = setcats(categorical(string(Tfix.fmt)),      fmtOptions);
        
        % undefinierte/leer fmt -> 'any'
        fmtStr = string(Tfix.fmt);
        fmtStr(fmtStr=="" | fmtStr=="<undefined>") = "any";
        Tfix.fmt = categorical(fmtStr, fmtOptions);


        % pattern als string
        if ismember('pattern', Tfix.Properties.VariableNames)
            Tfix.pattern = string(Tfix.pattern);
        else
            Tfix.pattern = strings(height(Tfix),1);
        end
        % max_scale als double >= 1.0
        if ismember('max_scale', Tfix.Properties.VariableNames)
            ms = Tfix.max_scale;
        elseif ismember('scale', Tfix.Properties.VariableNames)
            ms = Tfix.scale;  % rückwärtskompatibel
        else
            ms = ones(height(Tfix),1);
        end
        if iscell(ms), ms = string(ms); end
        if ~isnumeric(ms), ms = str2double(string(ms)); end
        ms(~isfinite(ms) | ms < 1.0) = 1.0;
        Tfix.max_scale = ms;
    end

    function T = coerceDataToTable(D, colNames)
        % Erzwingt eine table aus tbl.Data (table|cell)
        if istable(D)
            T = D; 
            return;
        end
        if iscell(D)
            cn = colNames;
            if isstring(cn), cn = cellstr(cn); end
            nColsWanted = numel(cn);
            nColsHave   = size(D,2);
    
            % pad / truncate auf korrekte Spaltenanzahl
            if nColsHave < nColsWanted
                D(:, end+1:nColsWanted) = {[]};
            elseif nColsHave > nColsWanted
                D = D(:, 1:nColsWanted);
            end
    
            T = cell2table(D, 'VariableNames', cn);
            return;
        end
        error('Unerwarteter Datentyp in tbl.Data: %s', class(D));
    end

    function vn = safeVarName(x)
        vn = char(matlab.lang.makeValidName(string(x)));
    end

    function ok = allROIsNamedProperly()
        T = coerceDataToTable(tbl.Data, tbl.ColumnName);
        if height(T)==0
            ok = false; 
            return;
        end
        % alles, was noch "_" ist, blockiert
        ok = all(~strcmp(string(T.name_roi), "_"));
    end
    
    function updateRunButtonState()
        if allROIsNamedProperly()
            btnRunOCR.Enable = 'on';
            btnPrepareOCR.Enable = 'on';
            lblStatus.Text   = 'Bereit: alle ROIs benannt.';
            % optional: Styles zurücksetzen
            try removeStyle(tbl); catch, end
        else
            btnRunOCR.Enable = 'off';
            btnPrepareOCR.Enable = 'off';
            lblStatus.Text   = 'Bitte allen ROIs Namen zuweisen (nicht "_").';
            % problematische Zeilen leicht rosa
            try
                bad = find(strcmp(string(coerceDataToTable(tbl.Data, tbl.ColumnName).name_roi), "_"));
                if ~isempty(bad)
                    try removeStyle(tbl); catch, end
                    st = uistyle('BackgroundColor', [1 0.95 0.95]);
                    addStyle(tbl, st, 'row', bad);
                end
            catch
            end
        end
    end

    function t = currentVideoAbs()
        if isPlaying
            t = tBaseAbs + toc(t0);
        else
            t = tBaseAbs;
        end
    end

    function stopAudio()
        if ~isempty(ap)
            try stop(ap); catch, end
            try delete(ap); catch, end          % Device freigeben
            ap = [];
        end
        try clear sound; catch, end             % Audiotreiber-Sauberkeit
        try audiodevreset; catch, end           % optional: Audio-Stack reset
    end

    function out = iff(cond, a, b), if cond, out=a; else, out=b; end, end

    % function secs = convertTimeTxtToSeconds(fmtStr, s)
    %     s = string(s);
    %     fmtStr = string(fmtStr);
    %     switch fmtStr
    %         case {"time_HH:MM:SS.cc","time_HH:MM:SS.SS","time_HH:MM:SS.SSS"}
    %             % tolerantes Parsing
    %             s = regexprep(s,'[^0-9:\.]','');
    %             if strlength(s) >= 8
    %                 try
    %                     % akzeptiere 2 oder 3 Nachkommastellen
    %                     if strlength(s)==10
    %                         secs = seconds(duration(s,'InputFormat','hh:mm:ss.SS'));
    %                     elseif strlength(s)>=11
    %                         secs = seconds(duration(extractBefore(s,12),'InputFormat','hh:mm:ss.SS'));
    %                     else
    %                         secs = seconds(duration(s,'InputFormat','hh:mm:ss'));
    %                     end
    %                 catch
    %                     secs = NaN;
    %                 end
    %             else
    %                 secs = NaN;
    %             end
    %         case "time_MM:SS"
    %             s = regexprep(s,'[^0-9:\.]','');
    %             try
    %                 secs = seconds(duration(s,'InputFormat','mm:ss'));
    %             catch
    %                 secs = NaN;
    %             end
    %         case "float"
    %             secs = str2double(s);
    %         case "integer"
    %             secs = str2double(s);
    %         otherwise
    %             % unbekanntes/any -> NaN (fällt auf out.time_s zurück)
    %             secs = NaN;
    %     end
    % end
    
    function i = integral_simple(t, elem)
        if numel(t)~=numel(elem) || numel(t)<2, i = zeros(size(t)); return; end
        i = [0; cumsum(diff(t) .* elem(1:end-1))];
    end

    function applyPreloadParams(p)
        % Start/Ende
        if isfield(p,'start_s') && isfield(p,'end_s')
            sldStart.Value = max(0, min(p.start_s, vidDuration));
            sldEnd.Value   = max(0, min(p.end_s,   vidDuration));
            onStartEndChanged(sldStart.Value, sldEnd.Value);
        end
        % Offset
        if isfield(p,'offset_s')
            sldOff.Value   = p.offset_s;
            lblOffVal.Text = sprintf('%.2f s', p.offset_s);
            updateOffset(p.offset_s);   % sync-linie & audio
        end
        % ROI-Tabelle
        if isfield(p,'roi_table') && ~isempty(p.roi_table)
            try
                Tload = sanitizeROIData(p.roi_table);
                tbl.Data = Tload;
                % (optional) vorhandene Rechtecke neu zeichnen
                try
                    for k=1:numel(rects), if isvalid(rects(k).h), delete(rects(k).h); end, end
                    rects = struct('h',{},'el',{});
                    for r = 1:height(Tload)
                        pos = str2double(strsplit(Tload.roi{r}));
                        if numel(pos)==4 && all(isfinite(pos))
                            rr = drawrectangle(axVid,'Position',pos,'InteractionsAllowed','all');
                            rects(end+1).h = rr; %#ok<AGROW>
                            rects(end).el = addlistener(rr,'ROIMoved',@onRectMoved);
                        end
                    end
                catch
                end
            catch
            end
        end
        % Acc- und v-Grenzen
        if exist('accMinEdit','var') && isfield(p,'acc_min'), accMinEdit.Value = p.acc_min; end
        if exist('accMaxEdit','var') && isfield(p,'acc_max'), accMaxEdit.Value = p.acc_max; end
        if exist('vMinEdit','var')   && isfield(p,'v_min'),   vMinEdit.Value   = p.v_min;   end
        if exist('vMaxEdit','var')   && isfield(p,'v_max'),   vMaxEdit.Value   = p.v_max;   end
    
        % Strecke & Korrektur (Dropdown/Checkbox)
        if exist('ddTrack','var') && isfield(p,'track') && ~isempty(p.track)
            items = string(ddTrack.Items);
            match = items(contains(items, p.track));
            if ~isempty(match)
                ddTrack.Value = match(1);
            end
        end
        if exist('cbNBR','var') && isfield(p,'apply_corr')
            cbNBR.Value = logical(p.apply_corr);
            cbNBR.Enable = iff(~strcmp(ddTrack.Value,'(keine)'),'on','off');
        end
        
        if exist('cbUseOCRv2', 'var') && isfield(p,'use_v')
            cbUseOCRv2.Value = logical(p.use_v);
        end
        if exist('edtTolPct2', 'var') && isfield(p,'tol_pct')
            edtTolPct2.Value = p.tol_pct;
        end
        if exist('gearing', 'var') && isfield(p,'i_axle')
            gearing.axle = p.i_axle;
        end
        if exist('gearing', 'var') && isfield(p,'gears')
            gearing.gears = p.gears;
        end
        if exist('edtRdyn2', 'var') && isfield(p,'r_dyn')
            edtRdyn2.Value = p.r_dyn;
        end
        if exist('cbLowGear2', 'var') && isfield(p,'prefer_low')
            cbLowGear2.Value = logical(p.prefer_low);
        end
        if exist('edtNFFT2', 'var') && isfield(p,'nfft')
            edtNFFT2.Value = p.nfft;
        end
        if exist('edtOvPerc2', 'var') && isfield(p,'ovPerc')
            edtOvPerc2.Value = p.ovPerc;
        end
        if exist('edtFmax2', 'var') && isfield(p,'fmax')
            edtFmax2.Value = p.fmax;
        end
        if exist('edtOrd2', 'var') && isfield(p,'order')
            edtOrd2.Value = p.order;
        end

    
        % Labels/Status aktualisieren
        lblStartVal.Text = sprintf('%.2f s', sldStart.Value);
        lblEndVal.Text   = sprintf('%.2f s', sldEnd.Value);
        if ~isempty(hStart) && isgraphics(hStart), hStart.Value = sldStart.Value; end
        if ~isempty(hEnd) && isgraphics(hEnd),   hEnd.Value   = sldEnd.Value;   end
        if ~isempty(hSync) && isgraphics(hSync),  hSync.Value  = sldStart.Value + sldOff.Value; end
        seekTo(sldStart.Value);
        updateNowLabels(sldStart.Value, max(1, round(sldStart.Value*vidFPS)));
        updateRunButtonState();
        lblStatus.Text = 'Parameter aus bestehendem OCR übernommen.';
    end

    function onRunRPM2(~,~)
        % ====== Indefinite Loading Progressbar ======
        d = uiprogressdlg(fig, ...
            'Title','Analysiere RPM...', ...
            'Message','Bitte warten, Analyse läuft...', ...
            'Indeterminate','on', ...
            'Cancelable','off');
        drawnow;
    
        try
            % ===== Guards =====
            if ~(exist('y','var') && ~isempty(y) && exist('fs','var') && fs>0)
                uialert(fig,'Kein Audio geladen.','Analyse RPM'); 
                close(d);
                return;
            end
    
            % ===== UI Parameter =====
            ord      = max(1, round(edtOrd2.Value));
            rpmMin   = edtRpmMin2.Value; 
            rpmMax   = edtRpmMax2.Value;
            useV     = cbUseOCRv2.Value;        % Checkbox "v berücksichtigen"
            preferLowGear = cbLowGear2.Value;   % Checkbox "niedrigster Gang bevorzugt"
    
            tolPct   = max(0, double(edtTolPct2.Value))/100;  % ±Toleranz in %
            tolAbs   = 120;                                   % min. ±120 rpm als Boden
    
            % ===== Zeit + Offset / Fenster =====

            % ===== SPEKTROGRAMM (robust für UIAxes) =====
            % 1) Parameter robust clampen
            Nsig = numel(y);
            nfft_ui   = max(256, round(edtNFFT2.Value));
            ovPerc    = max(0, min(99.9, edtOvPerc2.Value));
            nfft      = min(nfft_ui, max(64, Nsig));        % nie größer als Signal
            noverlap  = max(0, min(round(ovPerc/100*nfft), nfft-1));
            fmaxUI    = max(10, edtFmax2.Value);
            
            % 2) STFT
            win = hamming(nfft,'periodic');
            [S,F,T] = spectrogram(double(y), win, noverlap, nfft, fs, 'yaxis');
            Sabs = abs(S);
            if isempty(S) || isempty(F) || isempty(T)
                % Fallback (sehr kurzes Signal o.ä.)
                nfft = min(512, max(64, floor(Nsig/4)));
                noverlap = max(0, min(round(0.75*nfft), nfft-1));
                win = hamming(nfft,'periodic');
                [S,F,T] = spectrogram(double(y), win, noverlap, nfft, fs, 'yaxis');
            end
            Sdb = 20*log10(abs(S) + eps);
            
            % 3) Sichtfenster & CLim
            ao   = sldOff.Value;
            xWin = [sldStart.Value, sldEnd.Value] + ao;
            tMask = ~isempty(T) & (T >= (xWin(1)-ao)) & (T <= (xWin(2)-ao));
            if ~any(tMask) && ~isempty(T), tMask = true(size(T)); end
            fMask = (F <= fmaxUI); if ~any(fMask), fMask = true(size(F)); end
            
            vis = Sdb(fMask, tMask);
            if isempty(vis) || all(~isfinite(vis(:)))
                climRange = [-120 -60];
            else
                lo = prctile(vis(:),5); hi = prctile(vis(:),99);
                if ~isfinite(lo) || ~isfinite(hi) || lo>=hi, lo=-120; hi=-60; end
                climRange = [lo hi];
            end
            
            % 4) Zeichnen: hold AUS, reset, Handle setzen
            cla(axSpec2,'reset');                    % ACHTUNG: reset!
            hold(axSpec2,'off');                     % wichtig für UIAxes
            hSpecImg = imagesc(axSpec2, 'XData', T + ao, 'YData', F, 'CData', Sdb);
            set(hSpecImg,'HitTest','off');
            set(axSpec2,'YDir','normal','CLim',climRange);
            try 
                colormap(axSpec2,'turbo'); 
            catch 
                colormap(axSpec2,'parula'); 
            end
            title(axSpec2,'Spektrogramm'); ylabel(axSpec2,'f [Hz]'); xlabel(axSpec2,'t [s]');
            grid(axSpec2,'on');
            
            % 5) Limits
            if ~isempty(F), ylim(axSpec2,[0 min(fmaxUI, max(F))]); end
            if ~isempty(T), xlim(axSpec2, xWin); end
            drawnow;  % zwingt das Rendern im UI

            % ===== RPM aus Audio (Peak-Tracking im Band) =====
            fBandLo = max(0, (rpmMin/60) * ord);
            fBandHi = min((rpmMax/60) * ord, fmaxUI);
            bandMask = (F>=fBandLo) & (F<=fBandHi);
            if ~any(bandMask), bandMask = (F<=fmaxUI); end
    
            FF   = F(:); dF = median(diff(FF));
            FFb  = FF(bandMask);
            Sab  = Sabs(bandMask,:);
            rpmAudio = nan(size(T));
            for k = 1:numel(T)
                col = Sab(:,k);
                if any(isfinite(col))
                    [~,ii] = max(col);
                    fpk = FFb(ii);
                    if ii>1 && ii<numel(FFb)
                        y1 = log(col(ii-1)+eps); y2 = log(col(ii)+eps); y3 = log(col(ii+1)+eps);
                        p  = 0.5*(y1 - y3)/(y1 - 2*y2 + y3);
                        fpk = fpk + p*dF;
                    end
                    rpmAudio(k) = 60 * fpk / ord;
                end
            end
    
            if any(isfinite(rpmAudio))
                dt  = median(diff(T));
                w   = max(3, round(0.20 / max(dt, eps)));
                rpmAudio = movmedian(rpmAudio, w, 'omitnan');
                rpmAudio = movmean(rpmAudio, max(3,round(w/2)), 'omitnan');
                if rpmMax>rpmMin
                    rpmAudio(rpmAudio<rpmMin | rpmAudio>rpmMax) = nan;
                    rpmAudio = fillmissing(rpmAudio,'linear',1,'EndValues','nearest');
                end
            end
    
            % ===== Geschwindigkeit + Gangauswahl =====
            % [v_t, v_val] = getSeriesFromProcessed({'v_Fzg_kmph'});
            T_v = table();

            if isfield(recordResult, "ocr") && isfield(recordResult.ocr, "cleaned")
                T_v = recordResult.ocr.cleaned;
            else
                LOG('ocr.cleaned nicht in recordResult vorhanden.');
            end

            tGrid = T + ao;                             
            v_atT = nan(size(tGrid));

            if ~isempty(T_v)

                % Lösche Zeitsprünge -> time_s soll linear hochsteigen
                diff_time_s = diff(T_v.time_s);
                while any(diff_time_s < 0)
                    T_v(diff_time_s < 0, :) = [];
                    diff_time_s = diff(T_v.time_s);
                end
    
                if ismember('t_s', T_v.Properties.VariableNames)
            	    % Falls es sowohl t_s und als auch time_s gibt
                    % Schauen ob t_s verwendbar ist
                    % sonst fallback auf time_s -> time_s überschreibt t_s
                    R = checkTimeRun(T_v.time_s, T_v.t_s);
                    if ~R.ok
                        T_v.t_s = T_v.time_s;
                    end
                else
                    T_v.t_s = T_v.time_s;
                end

                % Platzhalter
                corr_factor = 1.0;
                
                if ismember('v_Fzg_mph', T_v.Properties.VariableNames)
                    T_v.v_Fzg_kmph = T_v.v_Fzg_mph ./ 1.60934;
                end

                % Geschwindigkeits-Grenzen
                vmin = vMinEdit.Value; 
                vmax = vMaxEdit.Value;
                T_v( T_v.v_Fzg_kmph < vmin | T_v.v_Fzg_kmph > vmax , :) = [];
    
                % "Löcher" befüllen
                x = T_v.t_s;
                a = T_v.v_Fzg_kmph;
                a(isnan(a)) = interp1( ...
                    x(~isnan(a)), ...
                    a(~isnan(a)), ...
                    x(isnan(a)));
                T_v.v_Fzg_kmph = a;

                % Beschleunigungs-Plausibilität (immer aktiv; ohne Sprungbegrenzung)
                if height(T_v) >= 2
                    aMin = accMinEdit.Value; 
                    aMax = accMaxEdit.Value;

                    % rows mit ungültiger a entfernen, danach ggf. neu berechnen bis stabil
                    changed = true;
                    while changed && height(T_v) >= 2
                        a = [0; diff(T_v.v_Fzg_kmph./3.6) ./ diff(T_v.t_s)];
                        bad = ~isfinite(a) | a < aMin | a > aMax;
                        bad(1) = false;           % ersten Wert behalten
                        keep = ~bad;
                        newH = sum(keep);
                        changed = newH < height(T_v);
                        T_v = T_v(keep,:);
                    end
                    T_v.a_mps2 = [0; diff(T_v.v_Fzg_kmph./3.6) ./ diff(T_v.t_s)];
                end

                % Apply track correction
                s_target = NaN;
                if height(T_v) >= 2
                    T_v.s_m = integral_simple(T_v.t_s, T_v.v_Fzg_kmph./3.6);
                    
                    if strcmp(ddTrack.Value,'Nürburgring Nordschleife (20 832 m)')
                        s_target = 20832; 
                    elseif strcmp(ddTrack.Value,'Hockenheimring (4 574 m)')     
                        s_target = 4574;  
                    end
                    
                    delta_s_proz = abs(s_target - T_v.s_m(end))/s_target * 100;

                    applyCorr = cbNBR.Value && isfinite(s_target);
        
                    if applyCorr && T_v.s_m(end)>0

                        if delta_s_proz > 10 
                            msg = "Streckenlänge kann nicht korrigiert werden, da der Unterschied zu einer vollen Strecke mehr als 10% beträgt.";
                            uialert(fig, msg, 'Analyse RPM'); 
                            close(d);
                            return;
                        end

                        corr_factor = s_target / T_v.s_m(end);
                        T_v.v_Fzg_adj_kmph = T_v.v_Fzg_kmph * corr_factor;
                        T_v.s_adj_m        = integral_simple(T_v.t_s, T_v.v_Fzg_adj_kmph./3.6);
                    end
                end

                v_atT = [];
                try
                    if ismember('v_Fzg_adj_kmph', T_v.Properties.VariableNames)
                        % Geschwindigkeitsverlauf mit Korrektuxyr
                        v_atT = interp1(T_v.t_s + ao, T_v.v_Fzg_adj_kmph, tGrid, 'linear', 'extrap');  % km/h
                    else
                        % Fallback: normale Geschwindigkeitsverlauf
                        v_atT = interp1(T_v.t_s + ao, T_v.v_Fzg_kmph, tGrid, 'linear', 'extrap');  % km/h
                    end
                catch % if only 1 sample point is available
                end

                % Save
                recordResult.ocr.processed = T_v;  % Speichern der gesamten Auswertung als Tabelle
                
                recordResult.ocr.processed_info = struct( ...
                    'acc_min_mps2', accMinEdit.Value, ...
                    'acc_max_mps2', accMaxEdit.Value, ...
                    'v_min_kmph', vMinEdit.Value, ...
                    'v_max_kmph', vMaxEdit.Value, ...
                    'track', ddTrack.Value, ...
                    'apply_track_correction', logical(cbNBR.Value), ...
                    's_target_m', s_target, ...
                    'corr_factor', corr_factor ...
                    );

                % Ergebnisse in MAT-Datei speichern
                save(filePath, 'recordResult', '-v7.3');

            end
    
            gearRatios = gearing.gears(:).';            
            iAxle      = gearing.axle;                  
            Rdyn       = max(1e-6, edtRdyn2.Value);     
            v_mps      = v_atT ./ 3.6;
            wheelRPM   = (v_mps ./ (2*pi*Rdyn)) * 60;   
            rpmPredAll = wheelRPM(:) .* (iAxle .* gearRatios);
    
            gearIdx = nan(size(tGrid));
            rpmPredSel = nan(size(tGrid));
            rpmFinal   = nan(size(tGrid));
            
            if useV && ~isempty(gearRatios) && ~isempty(rpmPredAll)
                for k = 1:numel(tGrid)
                    predRow = rpmPredAll(k,:);  
                
                    % === Physikalische Plausibilitätsprüfung ===
                    % theoretische RPM außerhalb realistischer Grenzen (z. B. 800–rpmMax*1.2) ausschließen
                    predRow(predRow < rpmMin | predRow > rpmMax*1.1) = NaN;
                
                    % Falls kein valider Gang bleibt, nächste Iteration
                    if all(~isfinite(predRow)), continue; end
                
                    % Referenz bestimmen (Audio oder Mittelwert)
                    rpmRef = rpmAudio(k);
                    if ~isfinite(rpmRef)
                        rpmRef = median([rpmMin rpmMax]);
                    end
                    
                    % dynamische Toleranz um die prädizierte RPM
                    diffAll = abs(predRow - rpmRef);
                    
                    % ===== neue Auswahlregel =====
                    % 1) Kandidaten innerhalb Toleranz
                    %    (Toleranz immer anhand der zu prüfenden prädizierten Drehzahl)
                    tolPerGear = max(tolAbs, tolPct * max(predRow, 1));   % vektorisiert
                    cand = find(diffAll <= tolPerGear);
                    
                    if preferLowGear && ~isempty(cand)
                        % Wenn Checkbox an: niedrigsten Gang unter den tolerierten nehmen
                        idxClose = min(cand);
                    else
                        % Sonst (oder wenn keine Kandidaten): klassisch minimaler Fehler
                        [~, idxClose] = min(diffAll);
                    end
                    
                    % Übernahme
                    predBest = predRow(idxClose);
                    tolHere  = max(tolAbs, tolPct*max(predBest,1));  % für Audio-vs-Pred Entscheidung
                    
                    if isfinite(rpmAudio(k)) && abs(rpmAudio(k) - predBest) <= tolHere
                        gearIdx(k)   = idxClose;
                        rpmPredSel(k)= predBest;
                        rpmFinal(k)  = rpmAudio(k);
                    else
                        gearIdx(k)   = idxClose;
                        rpmPredSel(k)= predBest;
                        rpmFinal(k)  = predBest;
                    end

                end
   
                if any(isfinite(gearIdx))
                    dt = median(diff(tGrid));
                    wg = max(3, round(0.30 / max(dt, eps)));
                    gearIdx = round(movmedian(gearIdx, wg, 'omitnan'));
                end
            else
                % Nur Audio – keine geschwindigkeitsbasierte Auswahl
                rpmFinal = rpmAudio;
                gearIdx(:) = NaN;  % wichtig: altes gearIdx löschen
            end
    
            %% ===== Plot RPM =====
            cla(axRPM2);
            plot(axRPM2, tGrid, rpmFinal, 'LineWidth',1);
            grid(axRPM2,'on');
            xlabel(axRPM2,'t [s]');
            ylabel(axRPM2,'RPM');
            if rpmMax>rpmMin, ylim(axRPM2,[rpmMin rpmMax]); end
            xlim(axRPM2, xWin);
    
            %% ===== Plot Geschwindigkeit =====
            cla(axV2);
            if ~isempty(T_v)
                mask = (T_v.t_s + ao >= xWin(1)) & (T_v.t_s + ao <= xWin(2));
                try
                    plot(axV2, T_v.t_s(mask) + ao, T_v.v_Fzg_adj_kmph(mask), 'LineWidth',1);
                catch
                    plot(axV2, T_v.t_s(mask) + ao, T_v.v_Fzg_kmph(mask), 'LineWidth',1);
                end
                grid(axV2,'on');
                xlabel(axV2,'t [s]');
                ylabel(axV2,'km/h');
                xlim(axV2, xWin);
                % ylim(axV2,[min(0, vMinEdit.Value-5), vMaxEdit.Value+5]);
            end
    
            %% ===== PLOT GANG =====
            cla(axGear2);
            hold(axGear2,'on');
            
            % --- mögliche Gänge abhängig von Geschwindigkeit farblich hervorheben ---
            if ~isempty(gearRatios) && exist('v_atT','var') && any(isfinite(v_atT))
                v_now = median(v_atT(isfinite(v_atT)));   % mittlere Geschwindigkeit im Zeitfenster [km/h]
                v_mps = v_now / 3.6;
                rpm_at_v = (v_mps / (2*pi*Rdyn)) * 60 * iAxle * gearRatios;  % theoretische Motordrehzahl je Gang
            
                % Gänge im zulässigen RPM-Bereich behalten
                validGears = find(rpm_at_v >= rpmMin & rpm_at_v <= rpmMax);
                nG = numel(gearRatios);
            
                for g = 1:nG
                    if ismember(g, validGears)
                        % gut sichtbare, aber dezente Türkisfarbe
                        clr = [0.25 0.65 0.75];
                        lw  = 1.4;
                        alphaVal = 0.8;
                    else
                        % blasse Version derselben Farbe
                        clr = [0.75 0.85 0.90];
                        lw  = 1.0;
                        alphaVal = 0.5;
                    end
                    p = plot(axGear2, xWin, [g g], '--', ...
                        'Color', clr, 'LineWidth', lw, 'HandleVisibility','off');
                    p.Color(4) = alphaVal;  % Transparenz (MATLAB R2022b+)
                end
            else
                % Fallback falls keine Geschwindigkeit vorhanden
                nG = numel(gearRatios);
                for g = 1:nG
                    p = plot(axGear2, xWin, [g g], '--', ...
                        'Color',[0.75 0.85 0.90], 'LineWidth',1.0, 'HandleVisibility','off');
                    p.Color(4) = 0.5;
                end
            end
            
            % --- tatsächlicher Gang ---
            if useV
                if any(isfinite(gearIdx))
                    stairs(axGear2, tGrid, gearIdx, 'LineWidth',2.0, ...
                        'Color',[0.85 0.33 0.10]);  % orange (v-basiert)
                    % text(xWin(1)+0.2, max(gearIdx)+0.3, 'Gang (v-basiert)', ...
                    %     'Color',[0.85 0.33 0.10],'FontSize',9,'FontWeight','bold');
                end
            else
                [g_t, g_val] = getSeriesFromTnew({'numgear_GET'});
                if isempty(g_t)
                    [g_t, g_val] = getSeriesFromProcessed({'numgear_GET'});
                end
                if ~isempty(g_t) && ~isempty(g_val)
                    gv = double(str2double(string(g_val(:))));
                    mask = (g_t + ao >= xWin(1)) & (g_t + ao <= xWin(2));
                    if any(mask)
                        stairs(axGear2, g_t(mask)+ao, gv(mask), 'LineWidth',2.0, ...
                            'Color',[0 0.45 0.74]);  % blau (OCR)
                        % text(xWin(1)+0.2, max(gv)+0.3, 'Gang (OCR)', ...
                        %     'Color',[0 0.45 0.74],'FontSize',9,'FontWeight','bold');
                    end
                end
            end
            
            grid(axGear2,'on');
            xlabel(axGear2,'t [s]');
            ylabel(axGear2,'Gang #');
            xlim(axGear2,xWin);
            ylim(axGear2,[0.5, numel(gearRatios)+0.5]);
            hold(axGear2,'off');

    
            % ===== Sync-Linie aktualisieren =====
            if exist('hSync','var') && isgraphics(hSync)
                hSync.Value = sldStart.Value + ao;
            end
    
            % ===== Ergebnis speichern =====
            try
                temp_table = struct( ...
                    't_s_spec', tGrid.', ...
                    'rpm_audio', rpmAudio.', ...
                    'rpm_final', rpmFinal.', ...
                    'gear_est',  gearIdx.');

                % Umwandeln der Parameter in eine Tabelle für die Speicherung
                temp_table = struct2table(temp_table);
                
                % Speichern direkt unter recordResult (nicht unter ocr)
                if ~isfield(recordResult, 'audio_rpm')
                    recordResult.audio_rpm = struct(); % Wenn es noch nicht existiert, initialisieren
                end

                audio_rpm = struct();
                audio_rpm.processed = temp_table;
                audio_rpm.params = struct('use_v',useV,'tol_pct',tolPct,'tol_abs',tolAbs, ...
                                     'i_axle',iAxle,'gears',gearRatios,'r_dyn',Rdyn, ...
                                     'prefer_low',preferLowGear,'nfft',nfft,'ovPerc',ovPerc,'fmax',fmaxUI,'order',ord);

                recordResult.audio_rpm = audio_rpm;  % Speichern der gesamten Auswertung als Tabelle
                
                % Ergebnisse in MAT-Datei speichern
                save(filePath, 'recordResult', '-v7.3');
            catch
            end
    
        catch ME
            warning(ME.identifier, 'Analyse RPM Fehler: %s', ME.message);
        end
    
        % ====== Progressbar schließen ======
        close(d);
    
        % ===== Lokale Helperfunktionen =====
        function [tser, yser] = getSeriesFromTnew(cands)
            tser=[]; yser=[];
            try
                if exist('T_new','var') && istable(T_new) && ismember('t_s',T_new.Properties.VariableNames)
                    tser = double(T_new.t_s(:));
                    for i=1:numel(cands)
                        nm=cands{i};
                        if ismember(nm,T_new.Properties.VariableNames) && ~all(ismissing(T_new.(nm)))
                            yser = toDouble(T_new.(nm)(:)); return
                        end
                    end
                end
            catch
                tser=[]; yser=[]; 
            end
        end
    
        function [tser, yser] = getSeriesFromCleaned(cands)
            tser=[]; yser=[];
            try
                if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'cleaned') && istable(recordResult.ocr.cleaned)
                    P = recordResult.ocr.cleaned;
                    timeFound = false;
                    % 1. Wahl -> t_s (aus OCR)
                    if ismember('t_s',P.Properties.VariableNames) && isnumeric(P.("t_s"))
                        param = "t_s";
                        timeFound = true;
                    % 2. Wahl -> time_s (nicht aus OCR)
                    elseif ismember('time_s',P.Properties.VariableNames) && isnumeric(P.("time_s"))
                        param = "time_s"
                        timeFound = true;
                    end

                    if timeFound
                        tser = double(P.(param)(:));
                        for i=1:numel(cands)
                            nm=cands{i};
                            if ismember(nm,P.Properties.VariableNames) && ~all(ismissing(P.(nm)))
                                yser = toDouble(P.(nm)(:)); return
                            end
                        end
                    end
                end
            catch 
                tser=[]; yser=[]; 
            end
        end

        function [tser, yser] = getSeriesFromProcessed(cands)
            tser=[]; yser=[];
            try
                if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'processed') && istable(recordResult.ocr.processed)
                    P = recordResult.ocr.processed;
                    timeFound = false;
                    % 1. Wahl -> t_s (aus OCR)
                    if ismember('t_s',P.Properties.VariableNames) && isnumeric(P.("t_s"))
                        param = "t_s";
                        timeFound = true;
                    % 2. Wahl -> time_s (nicht aus OCR)
                    elseif ismember('time_s',P.Properties.VariableNames) && isnumeric(P.("time_s"))
                        param = "time_s"
                        timeFound = true;
                    end

                    if timeFound
                        tser = double(P.(param)(:));
                        for i=1:numel(cands)
                            nm=cands{i};
                            if ismember(nm,P.Properties.VariableNames) && ~all(ismissing(P.(nm)))
                                yser = toDouble(P.(nm)(:)); return
                            end
                        end
                    end
                end
            catch 
                tser=[]; yser=[]; 
            end
        end
    
        function x = toDouble(col)
            if isnumeric(col), x=double(col); return; end
            if iscell(col),    x=str2double(string(col)); return; end
            if isstring(col) || ischar(col), x=str2double(string(col)); return; end
            if iscategorical(col), x = str2double(string(col)); return; end
            try x=double(col); catch, x=str2double(string(col)); end
        end
    end

    



    function openGearingDialogTable()
        % Robuster Tabellen-Dialog für Achse + Gänge
        d  = uifigure('Name','Getriebe','Position',[100 100 560 320]);
        gd = uigridlayout(d,[4 4]);
        gd.RowHeight   = {30, 26, '1x', 36};
        gd.ColumnWidth = {'1x','1x','1x','1x'};
    
        % --- Achse ---
        lblAx = uilabel(gd);
        lblAx.Text = 'Achsübersetzung i_{Achse}';
        lblAx.HorizontalAlignment = 'right';
        lblAx.Layout.Row = 1;
        lblAx.Layout.Column = [1 2];
    
        edtAx = uieditfield(gd,'numeric');
        edtAx.Value  = gearing.axle;
        edtAx.Limits = [eps Inf];
        edtAx.Layout.Row    = 1;
        edtAx.Layout.Column = [3 4];
    
        % --- Überschrift Tabelle ---
        lblGG = uilabel(gd);
        lblGG.Text = 'Gänge (Nr / i_{Gang})';
        lblGG.HorizontalAlignment = 'left';
        lblGG.Layout.Row = 2;
        lblGG.Layout.Column = [1 2];
    
        % --- Tabelle der Gänge ---
        gears0 = gearing.gears(:);
        if isempty(gears0), gears0 = 1; end
        T = table((1:numel(gears0)).', gears0, 'VariableNames', {'Gang','i_Gang'});
    
        tblG = uitable(gd);
        tblG.Data = T;
        tblG.ColumnEditable = [false true];
        tblG.RowName = {};
        tblG.Layout.Row = 3;
        tblG.Layout.Column = [1 4];
    
        % --- Buttons ---
        btnAdd = uibutton(gd,'Text','+ Gang');
        btnAdd.Layout.Row = 4; btnAdd.Layout.Column = 1;
        btnAdd.ButtonPushedFcn = @(~,~) addRow();
    
        btnDel = uibutton(gd,'Text','– Gang');
        btnDel.Layout.Row = 4; btnDel.Layout.Column = 2;
        btnDel.ButtonPushedFcn = @(~,~) delRow();
    
        btnCancel = uibutton(gd,'Text','Abbrechen');
        btnCancel.Layout.Row = 4; btnCancel.Layout.Column = 3;
        btnCancel.ButtonPushedFcn = @(~,~) close(d);
    
        btnOK = uibutton(gd,'Text','Übernehmen');
        btnOK.Layout.Row = 4; btnOK.Layout.Column = 4;
        btnOK.ButtonPushedFcn = @(~,~) apply();
    
        % ---- Helpers ----
        function addRow()
            T = tblG.Data;
            nextIdx = height(T) + 1;
            T = [T; {nextIdx, 1.00}];
            tblG.Data = T;
        end
    
        function delRow()
            T = tblG.Data;
            sel = tblG.Selection;
            if isempty(sel), return; end
            rows = unique(sel(:,1));
            keep = true(height(T),1);
            keep(rows) = false;
            T = T(keep,:);
            % Neu durchnummerieren
            if isempty(T)
                T = table(1, 1.00, 'VariableNames', {'Gang','i_Gang'});
            else
                T.Gang = (1:height(T)).';
            end
            tblG.Data = T;
        end
    
        function apply()
            T = tblG.Data;
            g = double(T.i_Gang);
            g = g(isfinite(g) & g>0);
            if isempty(g)
                uialert(d,'Bitte mindestens einen gültigen Gang (>0) angeben.','Hinweis');
                return;
            end
            gearing.axle  = max(edtAx.Value, eps);
            gearing.gears = g(:).';
            close(d);
        end
    end
   
    function onStopOCR(~,~)
        % nur Flag setzen; Loop beendet sich selbst beim nächsten drawnow
        ocrAbortRequested = true;
        btnRunOCR.Text = 'Stoppe …';
        btnRunOCR.Enable = 'off';    % Doppel-Klicks vermeiden
        btnPrepareOCR.Enable = 'off';
        pbSet(pbValue, 'OCR: Abbruch angefordert …');
        lblStatus.Text = 'OCR: Abbruch angefordert …';
    end
    
    function resetRunButton()
        btnRunOCR.Text = 'Run OCR (Start→End)';
        btnRunOCR.ButtonPushedFcn = @onRunOCR;
        btnRunOCR.Enable = 'on';
        btnPrepareOCR.Enable = 'on';
    end

    function dt = minWindowDt()
        % sichere Mindestlänge des Analysefensters
        dt = max([1/vidFPS, 0.01]);
        if ~isempty(fs) && isnumeric(fs) && isfinite(fs) && fs > 0
            dt = max(dt, 1/fs);
        end
    end
    
    function restoreAudioToInitial()
        needsRestore = isempty(y) || isempty(fs) || ~isfinite(fs) || fs <= 0 || numel(y) < 2;
    
        if needsRestore
            if ~isempty(y_init) && ~isempty(fs_init) && isfinite(fs_init) && fs_init > 0 && numel(y_init) >= 2
                y = y_init; fs = fs_init; audioPath = audioPath_init;
            else
                try
                    if ~isempty(audioPath) && isfile(audioPath)
                        [y, fs] = audioread(audioPath);
                    elseif ~isempty(videoPath) && isfile(videoPath)
                        [ya, fa] = audioread(videoPath);
                        tmpWav = fullfile(tempdir, ['tmp_audio_', char(java.util.UUID.randomUUID), '.wav']);
                        audiowrite(tmpWav, ya, fa);
                        audioPath = tmpWav; y = ya; fs = fa;
                    else
                        y = []; fs = [];
                    end
                catch
                    y = []; fs = [];
                end
            end
        end
    
        % Immer normalisieren, egal ob „needsRestore“ oder nicht
        [yNorm, ok] = normalizeAudioVector(y);
        if ok, y = yNorm; end
    
        refreshAudioPlot();
        ensureAudioWindow();
    end

    
    function ensureAudioWindow()
        % klemmt Start/Ende in die aktuelle Audiolänge mit Mindestbreite
        if isempty(y) || isempty(fs) || ~isfinite(fs) || fs <= 0 || numel(y) < 2
            return
        end
        audDur = numel(y)/fs;
        dt = minWindowDt();
    
        sldStart.Value = min( max(0, sldStart.Value), max(0, audDur - dt) );
        sldEnd.Value   = min( max(sldStart.Value + dt, sldEnd.Value), audDur );
    
        onStartEndChanged(sldStart.Value, sldEnd.Value);
    end
    
    function refreshAudioPlot()
        [yVec, ok] = normalizeAudioVector(y);
        if ~ok || isempty(fs) || ~isfinite(fs) || fs <= 0 || numel(yVec) < 2
            % Plot notfalls leeren, aber nicht craschen
            try
                if ~isempty(hAud) && isgraphics(hAud), delete(hAud); end
            catch
            end
            hAud = gobjects(0);
            return
        end
    
        y = yVec;  % global aktualisieren (späterer Code profitiert davon)
        tAud = (0:numel(y)-1)/fs;
    
        if isempty(hAud) || ~isgraphics(hAud) || ~ishandle(hAud) || ~isvalid(hAud)
            cla(axAud); hold(axAud,'on');
            hAud = plot(axAud, tAud, y, 'HitTest','off');
        else
            try
                set(hAud, 'XData', tAud, 'YData', y);
            catch
                % falls hAud keine skalar-Line ist -> neu zeichnen
                try delete(hAud); catch, end
                hAud = plot(axAud, tAud, y, 'HitTest','off');
            end
        end
        xlim(axAud, [0 max(tAud)]);
    
        if ~isempty(hStart) && isgraphics(hStart), hStart.Value = sldStart.Value; end
        if ~isempty(hEnd)   && isgraphics(hEnd),   hEnd.Value   = sldEnd.Value;   end
        if ~isempty(hSync)  && isgraphics(hSync),  hSync.Value  = sldStart.Value + sldOff.Value; end
    end

    
    function [yvec, ok] = normalizeAudioVector(yin)
        ok = true;
        % Tabellen u.ä. nach Array wandeln
        if istable(yin) || istimetable(yin)
            try
                yin = table2array(yin);
            catch
                ok = false; yvec = []; return;
            end
        end
        if isempty(yin) || ~isnumeric(yin)
            ok = false; yvec = []; return;
        end
        if ismatrix(yin)
            yin = squeeze(yin);
        end
        if size(yin,2) > 1            % Stereo -> Mono
            yin = mean(yin,2);
        end
        if ~isvector(yin)
            ok = false; yvec = []; return;
        end
        yvec = double(yin(:));         % Spaltenvektor erzwingen
    end

    % Helper (am Ende der Datei / bei deinen anderen lokalen Funktionen)
    function toggleCbNBR(src, cb)
        if strcmp(src.Value,'(keine)'), cb.Enable = 'off'; else, cb.Enable = 'on'; end
    end

    % ========================================================================
    % === DROP-IN C: LOKALE FUNKTIONEN – ANS DATEIENDE KOPIEREN ==============
    % ========================================================================
    
    function roi = getActualTrackRoi(Troi, idxTrackROI)
        % get ROI of track (track_minimap)
        roiStr = string(Troi.roi{idxTrackROI});
        roiNum = str2double(strsplit(roiStr));
        assert(numel(roiNum)==4 && all(isfinite(roiNum)), 'track_minimap ROI ist ungültig.');
        roi = roiNum(:).';   % [x y w h]
        assert(all(roi(3:4)>10), 'track_minimap ROI ist zu klein.');
    end

    function choiceCalibration = showActualCalibAndChoose(roi, videoHandle, trackName, trkCalSlim)

        ptsMini = trkCalSlim.ptsMini;

        % Repräsentative Frames ziehen (robust)
        numRep = 30;                         % vorher 7
        repFrames = getRepresentativeFrames(videoHandle, numRep);
        miniRGB  = cellfun(@(fr) imcrop(fr, roi), repFrames, 'uni',0);
        mm = uint8(median(cat(4, miniRGB{:}), 4));   % stabile Median-Minimap
        mask = buildTrackMask_auto(mm);
    
        % Centerline zuerst laden (echte Strecke!)
        [centerline, ~, ~] = loadCenterlineForTrack(trackName);
        
        % 8 Minimap-Punkte + 8 Centerline-Referenzpunkte + Marker-Hint im selben Dialog
        ptsRefFixed = getFixedPointsForTrack(trackName);

        if ~isempty(ptsRefFixed)
            LOG('Track-Kalibrierung: feste 8 Referenzpunkte aktiv (N=%d).', size(ptsRefFixed,1));
        else
            LOG('Track-Kalibrierung: KEINE festen Referenzpunkte -> rechts 8x klicken.');
        end

        % Plot actual state
        [~, ~, ~, hf] = collectPointsMiniRefAndHint(...
            mm, mask, centerline, ptsRefFixed, ...
            ptsMini);

        % Ask the user whether to calibrate
        choiceCalibration = questdlg( ...
            'Soll die Karte neu kalibriert werden?', ...
            'Karte kalibrieren', ...
            'Behalten','Neukalibrieren','Behalten');

        % Close fig
        close(hf);
    end

    function [trkCal, trkCalSlim] = runTrackCalibration(roi, videoHandle, trackName, ~, startTime_s, trkCalSlim)

    % Kalibriert die Track-Minimap (Maske, 8 Punkte, Warp, Farbmodell).
    % videoHandle: erwartet .NumFrames und .getFrame(i) -> RGB
    % trackName:   String (z.B. 'Nuerburgring')
    % parentFig:   Haupt-figure (nur für Dialoge optional)
    % ... letzter Parameter: startTime_s = sldStart.Value

        ptsMini = [];
        marker = [];

        if ~isempty(trkCalSlim) % overwrite if available
            roi = trkCalSlim.roi;
            ptsMini = trkCalSlim.ptsMini;
            marker = trkCalSlim.marker;
        end

        % Repräsentative Frames ziehen (robust)
        numRep = 30;                         % vorher 7
        repFrames = getRepresentativeFrames(videoHandle, numRep);
        miniRGB  = cellfun(@(fr) imcrop(fr, roi), repFrames, 'uni',0);
        mm = uint8(median(cat(4, miniRGB{:}), 4));   % stabile Median-Minimap
        mask = buildTrackMask_auto(mm);
    
        % Centerline zuerst laden (echte Strecke!)
        [centerline, s_total, sCum] = loadCenterlineForTrack(trackName);
        
        % 8 Minimap-Punkte + 8 Centerline-Referenzpunkte + Marker-Hint im selben Dialog
        ptsRefFixed = getFixedPointsForTrack(trackName);

        if ~isempty(ptsRefFixed)
            LOG('Track-Kalibrierung: feste 8 Referenzpunkte aktiv (N=%d).', size(ptsRefFixed,1));
        else
            LOG('Track-Kalibrierung: KEINE festen Referenzpunkte -> rechts 8x klicken.');
        end

        try
            [ptsMini, ptsRef, markerHint, hf] = collectPointsMiniRefAndHint(...
                mm, mask, centerline, ptsRefFixed, ...
                ptsMini);
            close(hf);
        catch ME    
            % Nutzerabbruch oder Fehler in der Punktwahl -> komplettes OCR abbrechen
            error('Track:CalibrationAborted', 'Kalibrierung abgebrochen: %s', ME.message);
        end

        % Warp: Minimap (moving) -> Centerline-Referenzpunkte (fixed)
        warp  = buildWarpFromPointsSimilarity_(ptsMini, ptsRef);

        if isempty(marker)
            % === EIN Start-Frame laden (Startzeit) und 1x Marker klicken ===
            okStart = false;
            if isa(videoHandle, 'VideoReader')
                okStart = true;
            end

            if okStart
                [hsv_mu, hsv_sig] = pickMarkerColor_OneClick_v2(videoHandle, mask, roi, startTime_s);
            else
                hsv_mu  = []; 
                hsv_sig = [];
            end

            % Marker-Initialisierung über Median-Stack + Hint
            marker = initMarkerModel_(cat(4, miniRGB{:}), mask, markerHint);
            if ~isempty(hsv_mu),  marker.hsv_mu  = hsv_mu;  end
            if ~isempty(hsv_sig), marker.hsv_sig = hsv_sig; end
        end

        % speichern
        trkCal = struct( ...
            'roi', roi, ...
            'mask', mask, ...
            'warp', warp, ...
            'marker', marker, ...
            'centerline', centerline, ...
            's_total', s_total, ...
            'sCum', sCum, ...
            'ptsMini', ptsMini, ...
            'ptsRef', ptsRef, ...
            'marker_hint', markerHint);

        trkCalSlim = struct(...
            'roi', roi, ...
            'ptsMini', ptsMini, ...
            'marker', marker);

    end

    function [mu, sig] = pickMarkerColor_OneClick_v2(vr, trackMask, roi, startTime_s)
    % Modales Popup: EIN Frame (über Slider wählbar), EIN Klick auf Marker.
    % Nach Klick: HSV-Statistik (Median, IQR+0.02), Fortsetzen-Button freigeben.
    %
    % Inputs:
    %   vr          VideoReader
    %   trackMask   (optional) logische Maske im ROI-Ausschnitt (wird gelb umrissen)
    %   roi         [x y w h] im Videobild (double)
    %   startTime_s Startzeit (Sekunden)
    %
    % Outputs:
    %   mu  [H S V]
    %   sig [dH dS dV]
    
        % ---------- Defaults / Validation ----------
        mu = []; sig = [];
        if nargin < 2, trackMask = []; end
        if nargin < 3 || isempty(roi), roi = [1 1 vr.Width vr.Height]; end
        if nargin < 4 || ~isscalar(startTime_s) || ~isfinite(startTime_s), startTime_s = 0; end
        roi = double(roi(:).');  % ensure row vector
    
        % ---------- Figure & UI ----------
        hf = figure('Name','Marker-Farbkalibrierung (1 Klick)', ...
                    'NumberTitle','off', ...
                    'Position',[240 240 1000 640], ...
                    'WindowStyle','modal', ...
                    'Color','w', ...
                    'Visible','on');
    
        ax = axes('Parent',hf,'Units','normalized','Position',[0.05 0.18 0.68 0.78]);
        uicontrol('Style','text','Parent',hf,'Units','normalized', ...
            'Position',[0.05 0.03 0.15 0.05], 'String','Vorschauzeit (s):', ...
            'HorizontalAlignment','left','FontWeight','bold');
    
        sld = uicontrol('Style','slider','Parent',hf,'Units','normalized', ...
            'Position',[0.20 0.045 0.40 0.035], ...
            'Min',0,'Max',max(0.01,vr.Duration),'Value',max(0,min(vr.Duration-1e-6,startTime_s)));
    
        txtT = uicontrol('Style','text','Parent',hf,'Units','normalized', ...
            'Position',[0.62 0.03 0.10 0.05], ...
            'String',sprintf('t = %.2f s',get(sld,'Value')), ...
            'HorizontalAlignment','left');
    
        btnUse = uicontrol('Style','pushbutton','Parent',hf,'Units','normalized', ...
            'Position',[0.78 0.60 0.18 0.08], 'String','Marker wählen', ...
            'FontWeight','bold', 'Callback',@onUse);
    
        btnGo  = uicontrol('Style','pushbutton','Parent',hf,'Units','normalized', ...
            'Position',[0.78 0.48 0.18 0.08], 'String','Mit OCR fortsetzen', ...
            'Enable','off', 'FontWeight','bold', 'Callback',@onProceed);
    
        txtMsg = uicontrol('Style','text','Parent',hf,'Units','normalized', ...
            'Position',[0.75 0.18 0.22 0.25], 'String','Wähle Zeit und klicke "Marker wählen".', ...
            'HorizontalAlignment','left', 'Max',2,'BackgroundColor','w');
    
        % Zustandsobjekt in AppData
        st = struct('haveSelection',false, 'mu',[], 'sig',[], 'hDot',gobjects(1), ...
                    'frozenTime',get(sld,'Value'));
        setappdata(hf,'state',st);
    
        % Slider-Callback
        set(sld,'Callback',@onSlide);
    
        % Beim Schließen: sauber abbrechen
        set(hf,'CloseRequestFcn',@(src,evt) onClose());
    
        % ---------- Erste Anzeige ----------
        refreshAt(get(sld,'Value'));
    
        % (Optional) trackMask anzeigen, falls vorhanden
        overlayTrackMask();
    
        % Blockieren, bis "Mit OCR fortsetzen" gedrückt wird oder Fenster zu
        uiwait(hf);
    
        % Falls Fenster noch existiert (onProceed schließt es)
        if isvalid(hf), delete(hf); end
    
        % ---------- Nested Functions ----------
    
        function onSlide(~,~)
            if strcmp(get(sld,'Enable'),'off')
                % Frame ist eingefroren -> Slider ignorieren
                return;
            end
            t = get(sld,'Value');
            set(txtT,'String',sprintf('t = %.2f s',t));
            refreshAt(t);
            setappdata(hf,'state',setfield(getappdata(hf,'state'),'frozenTime',t));
        end
    
        function refreshAt(t)
            I = readFrameAtTime(vr, t);
            try
                I_crop = imcrop(I, roi);
                if isempty(I_crop), I_crop = I; end
            catch
                I_crop = I;
            end
            imshow(I_crop,'Parent',ax);
            axis(ax,'image');
            title(ax,sprintf('t = %.2f s (eingefroren: %s)', t, onOffStr(strcmp(get(sld,'Enable'),'off'))));
            drawnow;
        end
    
        function overlayTrackMask()
            if isempty(trackMask), return; end
            Ishown = getimage(ax);
            if ~isequal(size(trackMask,1),size(Ishown,1)) || ~isequal(size(trackMask,2),size(Ishown,2))
                % Maskengröße auf Anzeigegröße anpassen
                try
                    trackMaskR = imresize(logical(trackMask), [size(Ishown,1) size(Ishown,2)], 'nearest');
                catch
                    trackMaskR = [];
                end
            else
                trackMaskR = logical(trackMask);
            end
            if ~isempty(trackMaskR)
                hold(ax,'on');
                B = bwboundaries(trackMaskR);
                for k=1:numel(B)
                    plot(ax, B{k}(:,2), B{k}(:,1), '-', 'Color',[1 1 0], 'LineWidth',1.0); % gelb
                end
                hold(ax,'off');
            end
        end
    
        function onUse(~,~)
            % Frame einfrieren, Slider deaktivieren
            set(sld,'Enable','off');
            set(btnUse,'Enable','off');
            set(btnGo,'Enable','off');
            updateMsg('Klicke 1× auf den Marker (ESC = abbrechen) …');
    
            % Fokus auf Achse, einmaliger Klick
            figure(hf); axes(ax);
            [cx, cy, btn] = ginput(1);
    
            % Nach ginput: Use-Button wieder aktivieren (erneut wählen erlauben)
            set(btnUse,'Enable','on');
    
            if isempty(cx) || btn==27
                updateMsg('Auswahl abgebrochen. Du kannst "Marker wählen" erneut drücken.');
                % Slider bleibt eingefroren – gewünschtes Verhalten
                return;
            end
    
            % Vorherigen Punkt löschen
            st = getappdata(hf,'state');
            if isgraphics(st.hDot), delete(st.hDot); end
            hold(ax,'on');
            st.hDot = plot(ax, cx, cy, 'ro', 'MarkerFaceColor','r', 'MarkerSize', 6);
            hold(ax,'off');
    
            % Patch aus angezeigtem (bereits gecropptem) Bild ziehen
            Ishown = getimage(ax); % das imshowte ROI-Bild
            r = 5;
            [H,W,~] = size(Ishown);
            x1 = max(1, round(cx)-r); x2 = min(W, round(cx)+r);
            y1 = max(1, round(cy)-r); y2 = min(H, round(cy)+r);
            patch = Ishown(y1:y2, x1:x2, :);
    
            % HSV-Statistik
            hsv = rgb2hsv(im2double(patch));
            Hh = hsv(:,:,1); Ss = hsv(:,:,2); Vv = hsv(:,:,3);
    
            mH = median_no_nan(Hh(:));  mS = median_no_nan(Ss(:));  mV = median_no_nan(Vv(:));
            sH = iqr_no_nan(Hh(:));     sS = iqr_no_nan(Ss(:));     sV = iqr_no_nan(Vv(:));
    
            st.mu  = [mH, mS, mV];
            st.sig = [sH+0.02, sS+0.02, sV+0.02];
            % Mindestbreiten
            st.sig = max(st.sig, [0.03 0.05 0.05]);
    
            st.haveSelection = true;
            setappdata(hf,'state',st);
    
            % Fortsetzen freigeben, Status anzeigen
            set(btnGo,'Enable','on');
            updateMsg(sprintf('Marker gesetzt. μ=[%.3f %.3f %.3f], σ=[%.3f %.3f %.3f].\nDu kannst erneut "Marker wählen" klicken oder "Mit OCR fortsetzen".', ...
                st.mu(1),st.mu(2),st.mu(3), st.sig(1),st.sig(2),st.sig(3)));
        end
    
        function onProceed(~,~)
            st = getappdata(hf,'state');
            if ~st.haveSelection
                updateMsg('Bitte zuerst "Marker wählen" klicken und den Marker setzen.');
                return;
            end
            % Outputs setzen und schließen
            mu  = st.mu;
            sig = st.sig;
            uiresume(hf);
        end
    
        function onClose()
            % Fenster schließen -> leere Outputs
            try uiresume(hf); catch, end
            try delete(hf); catch, end
        end
    
        function I = readFrameAtTime(vr_, tsec)
            tsec = max(0, min(max(0, vr_.Duration-1e-6), tsec));
            vr_.CurrentTime = tsec;
            I = readFrame(vr_);
        end
    
        function updateMsg(s)
            if isgraphics(txtMsg)
                set(txtMsg,'String',s);
                drawnow;
            end
        end
    
        function s = onOffStr(tf)
            if tf, s = 'JA'; else, s = 'NEIN'; end
        end
    
        % ---- kleine, toolbox-freie Helfer ----
        function m = median_no_nan(x)
            x = x(~isnan(x));
            if isempty(x), m = NaN; else, m = median(x); end
        end
    
        function r = iqr_no_nan(x)
            x = x(~isnan(x));
            if isempty(x), r = NaN; return; end
            x = sort(x(:));
            q25 = quantile_lin(x, 0.25);
            q75 = quantile_lin(x, 0.75);
            r   = q75 - q25;
        end
    
        function q = quantile_lin(x, p)
            % Lineare Quantil-Interpolation ohne Toolbox
            n = numel(x);
            if n == 0, q = NaN; return; end
            idx = (n-1)*p + 1;
            lo = floor(idx); hi = ceil(idx);
            if lo == hi, q = x(lo); else, q = x(lo) + (idx-lo)*(x(hi)-x(lo)); end
        end
    end

    
    function mask = buildTrackMask_auto(rgb)
        % Stabile Minimap-Maske: hell (V hoch), entsättigt (S klein)
        hsv = rgb2hsv(rgb);
        H = hsv(:,:,1); %#ok<NASGU>
        S = hsv(:,:,2); 
        V = hsv(:,:,3);
        bw = V > 0.7 & S < 0.4;
        bw = imclose(bw, strel('disk',2));
        bw = imfill(bw, 'holes');
        mask = bwareafilt(bw, 1);   % größte Region
    end
    
    function warp = buildWarpFromPointsAdaptive_(ptsMini, centerline)
        % Einfache 1D-Parametrisierung beider Kurven und Mapping per Sample-Suche
        s = [0; cumsum(sqrt(sum(diff(centerline,1,1).^2,2)) )];
        s = s / s(end);
        N = size(ptsMini,1);
        t = linspace(0,1,N).';
        fx = griddedInterpolant(t, ptsMini(:,1), 'pchip');
        fy = griddedInterpolant(t, ptsMini(:,2), 'pchip');
        function XY = applyFun(uv)
            tt = linspace(0,1,400);
            uvx = fx(tt); uvy = fy(tt);
            d2 = (uv(1)-uvx).^2 + (uv(2)-uvy).^2;
            [~,iMin] = min(d2);
            XY = [interp1(linspace(0,1,numel(s)), centerline(:,1), tt(iMin), 'linear','extrap'), ...
                  interp1(linspace(0,1,numel(s)), centerline(:,2), tt(iMin), 'linear','extrap')];
        end
        warp = struct('applyFun', @applyFun);
    end
    
    function [C, s_total, sCum] = loadCenterlineForTrack(trackName)
    % Lädt die echte Centerline als XY [m] und berechnet s_total & sCum.
    % Unterstützt ddTrack.Value z.B.:
    % 'Nürburgring Nordschleife (20 832 m)'  -> lädt Nordschleife_2024_08_12.mat
    % 'Hockenheimring (4 574 m)'             -> (optional) lädt Hockenheim_*.mat
    
        tn = lower(string(trackName));
    
        if contains(tn, "nürburgring") || contains(tn, "nuerburgring") || contains(tn,"nordschleife")
            [C] = load_centerline_from_mat(...
                fullfile("reference_track_siesmann", "Nordschleife_2024_08_12.mat"));
        elseif contains(tn,"hockenheim")
            % Falls vorhanden, sonst diese Zeilen entfernen
            [C] = load_centerline_from_mat(...
                fullfile("reference_track_siesmann", "Hockenheim*.mat"));
        else
            error("Unbekannter Track-Name: %s. Bitte Strecke im Dropdown wählen.", trackName);
        end
    
        % Bogenlänge vorbereiten
        dP = diff(C,1,1);
        segLen = hypot(dP(:,1), dP(:,2));
        sCum = [0; cumsum(segLen)];
        s_total = sCum(end);
    end
    
    function C = load_centerline_from_mat(pattern)
    % Sucht die .mat-Datei in sinnvollen Orten und berechnet die Centerline aus Bnd.L2R_xyz__m
        matFile = find_mat_file(pattern);
    
        S = load(matFile);
        if ~isfield(S, "Bnd") || ~isfield(S.Bnd, "L2R_xyz__m")
            error("Datei %s enthält kein Feld Bnd.L2R_xyz__m.", matFile);
        end
    
        L2R = S.Bnd.L2R_xyz__m;           % Zellen: linke→rechte Spur
        left_cells  = cellfun(@(A) A(1,1:3),   L2R, 'UniformOutput', false);
        right_cells = cellfun(@(A) A(end,1:3), L2R, 'UniformOutput', false);
        P_left  = vertcat(left_cells{:});
        P_right = vertcat(right_cells{:});
        centerline_xyz_m = (P_left + P_right)/2;
    
        C = centerline_xyz_m(:,1:2);      % XY [m]
    end
    
    function f = find_mat_file(pattern)
    % Sucht eine passende .mat-Datei in: aktueller Ordner, Ordner des Videos, Ordner der App
        candidates = {};
    
        % 1) aktuelles Arbeitsverzeichnis
        L = dir(pattern); 
        candidates = [candidates; fullfile({L.folder},{L.name})'];
    
        % 2) Ordner des Videos (falls im Workspace vorhanden)
        try
            if evalin('base','exist(''videoPath'',''var'')')
                vp = evalin('base','videoPath'); 
                if isstring(vp) || ischar(vp), vdir = fileparts(char(vp)); 
                    L = dir(fullfile(vdir, pattern));
                    candidates = [candidates; fullfile({L.folder},{L.name})'];
                end
            end
        catch
        end
    
        % 3) Ordner dieser m-Datei
        try
            mdir = fileparts(mfilename('fullpath'));
            L = dir(fullfile(mdir, pattern));
            candidates = [candidates; fullfile({L.folder},{L.name})']; 
        catch
        end
    
        candidates = candidates(~cellfun(@isempty, candidates));
        if isempty(candidates)
            % letzte Chance: Dialog
            [f,p] = uigetfile('*.mat','Centerline-MAT wählen');
            if isequal(f,0), error('Keine Centerline-MAT gewählt.'); end
            out = fullfile(p,f);
        else
            out = candidates{1};
        end
        f = out;
    end

    
    function [pct, s_q, proj_xy] = progressOnPolylineWithProj_(C, XY, s_total, sCum)
        d2 = sum((C - XY).^2,2);
        [~,i0] = min(d2);
        i1 = max(1, i0-1); i2 = min(size(C,1), i0+1);
        candidates = [i1,i0,i2];
        bestS = 0; bestXY= C(i0,:); bestDist = inf;
        for k=1:numel(candidates)-1
            a = C(candidates(k),:); b = C(candidates(k+1),:);
            ab = b-a; t = max(0,min(1, dot(XY-a,ab)/dot(ab,ab)));
            p = a + t*ab; d = norm(XY-p);
            s_here = sCum(candidates(k)) + t*norm(ab);
            if d < bestDist, bestDist = d; bestS = s_here; bestXY = p; end
        end
        s_q = bestS; proj_xy = bestXY;
        pct = s_q / s_total;
    end
    
    function openCloseTrackDetails(~,~)
        h = getappdata(0,'TRACK_DETAILS_FIG');
        if isempty(h) || ~isvalid(h)
            h = figure('Name','Track-Details','NumberTitle','off','Position',[100 100 1200 800]);
            t = tiledlayout(h,2,2,'Padding','compact','TileSpacing','compact');
            ax1 = nexttile(t); ax2 = nexttile(t); ax3 = nexttile(t); ax4 = nexttile(t);
            setappdata(0,'TRACK_DETAILS_AX', struct('ax1',ax1,'ax2',ax2,'ax3',ax3,'ax4',ax4));
            setappdata(0,'TRACK_DETAILS_FIG', h);
        else
            delete(h); rmappdata(0,'TRACK_DETAILS_FIG'); rmappdata(0,'TRACK_DETAILS_AX');
        end
    end
    
    function updateTrackDetailsIfOpen(miniRGB, mask, uv, C, XY, proj_xy, tNow, pct100, ptsRef, ptsMini, warp)
        h = getappdata(0,'TRACK_DETAILS_FIG');
        if isempty(h) || ~isvalid(h), return; end
        ax = getappdata(0,'TRACK_DETAILS_AX');
    
        % 1) Minimap + Maske
        axes(ax.ax1); cla(ax.ax1); imshow(miniRGB,'Parent',ax.ax1); hold(ax.ax1,'on');
        visboundaries(ax.ax1, mask, 'Color','y'); title(ax.ax1,'Minimap + Maske');
    
        % 2) Minimap + Marker
        axes(ax.ax2); cla(ax.ax2); imshow(miniRGB,'Parent',ax.ax2); hold(ax.ax2,'on');
        if all(isfinite(uv)), plot(ax.ax2, uv(1), uv(2), 'o','LineWidth',1.2); end
        title(ax.ax2,'Marker');
    
        % 3) Centerline + Projektion
        axes(ax.ax3); cla(ax.ax3); 
        plot(ax.ax3, C(:,1), C(:,2), '-'); 
        hold(ax.ax3,'on'); 

        % --- 8 FixedPoints auf der Centerline (deine Referenzpunkte)
        if exist('ptsRef','var') && ~isempty(ptsRef)
            plot(ax.ax3, ptsRef(:,1), ptsRef(:,2), 'o--', ...
                'MarkerSize',7, 'MarkerFaceColor',[0.95 0.2 0.2], ...
                'MarkerEdgeColor','k', 'Color',[0.95 0.2 0.2]);
            % Nummern daneben
            for ii=1:size(ptsRef,1)
                text(ax.ax3, ptsRef(ii,1), ptsRef(ii,2), sprintf('  %d',ii), ...
                    'Color',[0.95 0.2 0.2], 'FontWeight','bold');
            end
        end
        
        % --- (optional) die 8 Minimap-Punkte in XY projiziert, zum Abgleich
        if exist('ptsMini','var') && ~isempty(ptsMini) && exist('warp','var') && isstruct(warp)
            XYmini = warp.applyFun(ptsMini);   % Nx2
            plot(ax.ax3, XYmini(:,1), XYmini(:,2), 's-', ...
                'MarkerSize',6, 'MarkerFaceColor',[0 0.6 1], ...
                'MarkerEdgeColor','k', 'Color',[0 0.6 1]);
        end

        axis(ax.ax3,'equal'); 
        grid(ax.ax3,'on');
        plot(ax.ax3, XY(1), XY(2), 'o','LineWidth',1.2);
        plot(ax.ax3, proj_xy(1), proj_xy(2), 'x','LineWidth',1.2);
        title(ax.ax3,'Centerline & XY/Proj');
    
        % 4) Fortschritt
        axes(ax.ax4); hold(ax.ax4,'on'); grid(ax.ax4,'on');
        al = getappdata(h,'al_progress');
        if isempty(al) || ~isvalid(al)
            cla(ax.ax4); al = animatedline('Parent',ax.ax4);
            setappdata(h,'al_progress', al);
            setappdata(h,'t0', tNow);
        end
        t0 = getappdata(h,'t0');
        addpoints(al, tNow-t0, pct100);
        xlabel(ax.ax4,'t [s]'); ylabel(ax.ax4,'Track [%]'); title(ax.ax4,'Fortschritt');
        drawnow limitrate
    end
    
    function repFrames = getRepresentativeFrames(videoHandle, K)
        % Liefert K repräsentative RGB-Frames für Median-Minimap usw.
        if isa(videoHandle, 'VideoReader')
            v = videoHandle;
            n = max(2, floor(v.Duration * v.FrameRate));      % geschätzte Frameanzahl
            idx = round(linspace(1, n, max(2, K)));
            tPrev = v.CurrentTime;                             % Zeit merken
            repFrames = cell(numel(idx),1);
            for j = 1:numel(idx)
                t = (idx(j)-1) / v.FrameRate;
                try
                    v.CurrentTime = max(0, min(t, v.Duration-1e-3));
                    repFrames{j} = readFrame(v);
                catch
                    % Fallback: beim Fehler letzten gültigen Frame wiederverwenden
                    if j>1 && ~isempty(repFrames{j-1})
                        repFrames{j} = repFrames{j-1};
                    else
                        v.CurrentTime = 0;
                        repFrames{j} = readFrame(v);
                    end
                end
            end
            % ursprüngliche Position wiederherstellen
            try v.CurrentTime = tPrev; catch, end
            return
        end
    
        % Generischer Adapter (struct mit .NumFrames und .getFrame(i))
        if isstruct(videoHandle) && isfield(videoHandle,'NumFrames') && isfield(videoHandle,'getFrame')
            n = max(2, videoHandle.NumFrames);
            idx = round(linspace(1, n, max(2, K)));
            repFrames = arrayfun(@(ii) videoHandle.getFrame(ii), idx, 'uni', 0);
            return
        end
    
        % Fallback: falls bereits ein einzelnes RGB-Frame übergeben wurde
        repFrames = {videoHandle};
    end

    function warp = buildWarpFromPointsSimilarity_(movingPoints, fixedPoints)
        tf = fitgeotrans(movingPoints, fixedPoints, 'similarity');
        warp.tform = tf;
        warp.model = 'SIMILARITY';
        warp.applyFun = @(UV) forwardPoints_(tf, UV);
    end
    
    function XY = forwardPoints_(tf, UV)
        [X,Y] = transformPointsForward(tf, UV(:,1), UV(:,2)); 
        XY = [X Y];
    end

    function marker = initMarkerModel_(miniFramesRGB, ~, markerHint)
        med = uint8(median(miniFramesRGB,4));
        medGray = rgb2gray(med);
        marker = struct();
        marker.bgGray = medGray;
        marker.prev_uv = [];
        if ~isempty(markerHint), marker.prev_uv = markerHint(:).'; end
        marker.hsv_mu = [0 1 1];            % Start grob (wird durch Hint stabilisiert)
        marker.hsv_sig = [0.2 0.2 0.2];
        marker.area_px = 20;
    end

    function [uv, ok, state] = detectMarkerMotionColor_(miniRGB, trackMask, state, marker)
        if ~isfield(state,'prev_uv') || isempty(state.prev_uv)
            state.prev_uv = marker.prev_uv;
        end
        hsv=rgb2hsv(miniRGB); H=hsv(:,:,1); S=hsv(:,:,2); V=hsv(:,:,3);
        dAng=atan2(sin(2*pi*(H-marker.hsv_mu(1))),cos(2*pi*(H-marker.hsv_mu(1))));
        zH=abs(dAng)/(2*pi)./max(marker.hsv_sig(1),0.02);
        zS=abs(S-marker.hsv_mu(2))./max(marker.hsv_sig(2),0.05);
        zV=abs(V-marker.hsv_mu(3))./max(marker.hsv_sig(3),0.05);
        colorScore=exp(-0.5*(zH.^2+zS.^2+zV.^2));
        bw_color = colorScore > 0.65;
    
        g = rgb2gray(miniRGB); if ~isa(g,'uint8'), g = im2uint8(g); end
        d1 = imabsdiff(g, marker.bgGray);
        bw_motion = d1 > 25;
    
        cand = (bw_color | bw_motion) & ~imdilate(trackMask, strel('disk',1));
        cand = bwareaopen(cand, 4);
    
        CC = bwconncomp(cand);
        if CC.NumObjects==0, ok=false; uv=state.prev_uv; return; end
        Sprop = regionprops(CC,'Area','Centroid','BoundingBox');
    
        best=-inf; uvBest=state.prev_uv;
        for i=1:CC.NumObjects
            A = Sprop(i).Area; C = Sprop(i).Centroid; bb=Sprop(i).BoundingBox;
            aspect = max(bb(3)/bb(4), bb(4)/bb(3));
            rectScore = exp(-((aspect-1.2)/0.6)^2);
            dprev = inf; 
            if ~isempty(state.prev_uv) && all(isfinite(state.prev_uv))
                dprev = hypot(C(1)-state.prev_uv(1), C(2)-state.prev_uv(2));
            end
            sA = exp(-((A-marker.area_px)/max(10,0.5*marker.area_px))^2);
            sD = exp(-(dprev/25)^2);
            score = 0.5*sA + 0.3*rectScore + 0.2*sD;
            if score>best, best=score; uvBest=C; end
        end
        uv = uvBest; ok=true; state.prev_uv = uv;
    end


    function P = getFixedPointsForTrack(trackName)
        tn = lower(string(trackName));
        if contains(tn,"nürburgring") || contains(tn,"nuerburgring") || contains(tn,"nordschleife")
            P = [ ...
                307.196               299.616;
                1978.42832378196      321.354522948525;
                3085.71261117950     -484.441468375425;
                3414.60893416886    -2534.56188167581;
                2301.84304138817    -4261.26757736999;
                87.274466593099     -5374.03347015068;
                -1031.33            -5077.18;
                -937.785740057097   -2912.79265311359 ];
        else
            P = []; % andere Strecken: leer -> weiterhin rechts klicken
        end
    end

    function [ptsMini, ptsRef, markerHint, hf] = collectPointsMiniRefAndHint(...
            minimapRGB, trackMask, centerline, ptsRefFixed, ...
            ptsMini)

        if nargin < 4, ptsRefFixed = []; end
    
        hf = figure('Name','8 Punkte (Referenz zuerst) + Marker-Hint', ...
                    'NumberTitle','off','Position',[80 80 1200 660], ...
                    'WindowStyle','modal','Visible','on');

        t = tiledlayout(hf,1,2,'Padding','compact','TileSpacing','compact');
    
        % --- RECHTS: Centerline + (sofort) Referenzpunkte ---
        axR = nexttile(t,2);
        plot(axR, centerline(:,1), centerline(:,2), 'k-'); hold(axR,'on');
        grid(axR,'on'); axis(axR,'equal');
        xlabel(axR,'X [m]'); ylabel(axR,'Y [m]');
    
        % ptsRef = [];                  % wird gefüllt (fest oder per Klick)
        colR   = [0.95 0.2 0.2];
    
        if ~isempty(ptsRefFixed)
            % Feste 8 Referenzpunkte sofort anzeigen
            assert(isequal(size(ptsRefFixed),[8 2]), 'fixedPoints muss 8x2 sein.');
            ptsRef = double(ptsRefFixed);
            plot(axR, ptsRef(:,1), ptsRef(:,2), 'o--', ...
                'MarkerSize', 9, 'LineWidth', 1.4, ...
                'MarkerFaceColor', colR, 'MarkerEdgeColor', 'k', ...
                'Color', colR, 'LineStyle','--');
            for i=1:8
                text(axR, ptsRef(i,1), ptsRef(i,2), sprintf('  %d',i), ...
                     'Color', colR, 'FontWeight','bold');
            end
            % Achsenlimits so wählen, dass Centerline+Punkte sicher sichtbar sind
            xAll = [centerline(:,1); ptsRef(:,1)];
            yAll = [centerline(:,2); ptsRef(:,2)];
            rx = range(xAll); if rx<=0, rx = 1; end
            ry = range(yAll); if ry<=0, ry = 1; end
            mx = 0.05*rx; my = 0.05*ry;
            xlim(axR, [min(xAll)-mx, max(xAll)+mx]);
            ylim(axR, [min(yAll)-my, max(yAll)+my]);
            title(axR,'Centerline (fix) – feste Referenzpunkte (1→8)');

        else
            % Keine festen Punkte → rechts 8 Klicks (falls du es so behalten willst)
            title(axR,'Centerline (fix) – klicke 8 Referenzpunkte (1→8)');
            ptsRef = zeros(8,2);
            for i=1:8
                [xr,yr] = ginput(1);
                if isempty(xr), error('Abbruch bei Ref-Punkt %d',i); end
                ptsRef(i,:) = [xr yr];
                plot(axR, xr, yr, 'o', 'MarkerSize',9, 'MarkerFaceColor', colR, 'MarkerEdgeColor','k');
                text(axR, xr, yr, sprintf('  %d',i), 'Color', colR, 'FontWeight','bold');
                if i>1, line(axR, ptsRef(i-1:i,1), ptsRef(i-1:i,2), 'Color', colR, 'LineStyle','--'); end
            end
        end
    
        % --- LINKS: Minimap + Maske (jetzt erst klicken) ---
        axL = nexttile(t,1);
        imshow(minimapRGB,'Parent',axL); hold(axL,'on');
        visboundaries(axL, trackMask, 'Color','y','LineWidth',1.2);
        title(axL,'Minimap (moving) – klicke nun 8 Punkte in gleicher Reihenfolge (1→8)');
    
        % Sorgt dafür, dass ginput-Klicks auf der linken Achse landen
        set(hf, 'CurrentAxes', axL);
    
        % Vor den ginput-Schleifen:
        oldPtr = get(hf,'Pointer');
        oldCData = get(hf,'PointerShapeCData');
        oldHot   = get(hf,'PointerShapeHotSpot');
        
        % 16x16 weißes Fadenkreuz (NaN = transparent, 1=schwarz, 2=weiß)
        C = NaN(16,16);
        C(8,:)  = 2;       % horizontale Linie in weiß
        C(:,8)  = 2;       % vertikale Linie in weiß
        C(8,8)  = 2;       % Zentrum
        set(hf,'Pointer','custom','PointerShapeCData',C,'PointerShapeHotSpot',[8 8]);
        
        % ... vorhandene ginput(1)-Schleifen bleiben unverändert ...
        
        % Nach allen Klicks (oder im catch/finally bei Abbruch) Pointer zurücksetzen:
        set(hf,'Pointer',oldPtr,'PointerShapeCData',oldCData,'PointerShapeHotSpot',oldHot);

        if isempty(ptsMini)
            ptsMini = zeros(8,2);
            colL = [0 0.6 1];
            for i=1:8
                [x,y] = ginput(1);
                if isempty(x), error('Abbruch bei Minimap-Punkt %d',i); end
                % Klick sicherstellen: falls nicht in axL, wiederholen
                while ~isPointInAxes(axL, [x y])
                    % kurze Hinweis-Überblendung möglich:
                    % text(axL, mean(xlim(axL)), mean(ylim(axL)), 'Bitte in der linken Grafik klicken', 'Color','r');
                    [x,y] = ginput(1);
                    if isempty(x), error('Abbruch bei Minimap-Punkt %d',i); end
                end
                ptsMini(i,:) = [x y];
                plot(axL, x, y, 'o', 'MarkerSize',7, 'MarkerFaceColor', colL, 'MarkerEdgeColor','k');
                text(axL, x, y, sprintf('  %d',i), 'Color', colL, 'FontWeight','bold');
                if i>1, line(axL, ptsMini(i-1:i,1), ptsMini(i-1:i,2), 'Color', colL, 'LineStyle','--'); end
            end
        else
            colL = [0 0.6 1];
            for i=1:8
                xi = ptsMini(i, 1);
                yi = ptsMini(i, 2);
                plot(axL, xi, yi, 'o', 'MarkerSize',7, 'MarkerFaceColor', colL, 'MarkerEdgeColor','k');
                text(axL, xi, yi, sprintf('  %d',i), 'Color', colL, 'FontWeight','bold');
                if i>1, line(axL, ptsMini(i-1:i,1), ptsMini(i-1:i,2), 'Color', colL, 'LineStyle','--'); end
            end
        end
    
        % --- Marker-Hint (in der Minimap) ---
        % title(axL,'Klicke jetzt auf den Marker (Hint, 1x) in der Minimap.');
        % [hx,hy,btn] = ginput(1);
        % if isempty(hx) || btn==27, error('Marker-Hint abgebrochen'); end
        % plot(axL, hx, hy, 'x', 'LineWidth', 1.5, 'Color', [1 0 0]);
        % markerHint = [hx hy];

        markerHint = [];
    
        % if flagCloseFig
        %     close(hf);
        % end
    end
    
    function tf = isPointInAxes(ax, pt)
        % Prüft, ob ein [x y]-Punkt innerhalb der Achse liegt (in Datenkoordinaten)
        xl = xlim(ax); yl = ylim(ax);
        tf = pt(1)>=xl(1) && pt(1)<=xl(2) && pt(2)>=yl(1) && pt(2)<=yl(2);
    end

    function t = slimTrack(trkCal)
    % Reduziert das Track-Struct auf das Nötigste für spätere Auswertungen/Sicht.
    % Speichert KEINE großen Bilder/Masken oder Funktionshandles.
    
        t = struct();
        t.version = 1;
    
        % 1) ROI (Pixelrechteck)
        if isfield(trkCal,'roi'), t.roi = trkCal.roi; end
    
        % 2) Centerline & Längen (als single, spart ~50%)
        if isfield(trkCal,'centerline'), t.centerline = single(trkCal.centerline); end
        if isfield(trkCal,'s_total'),    t.s_total    = single(trkCal.s_total);    end
        if isfield(trkCal,'sCum'),       t.sCum       = single(trkCal.sCum);       end
    
        % 3) Warp – NUR Modell + 3x3-Matrix T, keine Funktionshandles/Objekte
        T = [];
        if isfield(trkCal,'warp')
            w = trkCal.warp;
            % verschiedene Varianten robust abgreifen
            if isfield(w,'tform') && isobject(w.tform) && isprop(w.tform,'T')
                T = w.tform.T;
            elseif isfield(w,'T')
                T = w.T;
            end
        end
        t.warp = struct('model','SIMILARITY','T', single(T));
    
        % 4) Marker – nur Farb-/Größenparameter
        if isfield(trkCal,'marker')
            m = trkCal.marker;
            mu  = []; sig = []; area = [];
            if isfield(m,'hsv_mu'),  mu   = single(m.hsv_mu);  end
            if isfield(m,'hsv_sig'), sig  = single(m.hsv_sig); end
            if isfield(m,'area_px'), area = single(m.area_px); end
            t.marker = struct('hsv_mu',mu,'hsv_sig',sig,'area_px',area);
        else
            t.marker = struct('hsv_mu',[],'hsv_sig',[],'area_px',[]);
        end


    end



    % ========================================================================
    % === ENDE DROP-IN C =====================================================
    % ========================================================================

    function onLoadTT()
        [f,p] = uigetfile('*.mat','Messdatei (TT) laden');
        if isequal(f,0), return; end
        full = fullfile(p,f);
        try
            S = load(full,'TT');
            if ~isfield(S,'TT') || ~istimetable(S.TT)
                uialert(gcbf,'In der Datei wurde kein timetable "TT" gefunden.','Messdatei');
                return;
            end
            TT_meas = S.TT;
            ts = TT_meas.Properties.RowTimes;
            if isempty(ts)
                uialert(gcbf,'TT.Properties.RowTimes leer/ungültig.','Messdatei');
                TT_meas=[]; return;
            end
            cols = string(TT_meas.Properties.VariableNames);
            ddTTv.Items = cols; ddTTn.Items = cols;
            ddTTv.Enable='on'; ddTTn.Enable='on';
            % Heuristiken für Vorauswahl
            iV = find(contains(lower(cols),["kmh","km/h","v_fzg","speed"]),1);
            iN = find(contains(lower(cols),["rpm","n_mot","engine"]),1);
            if ~isempty(iV), ddTTv.Value = cols(iV); end
            if ~isempty(iN), ddTTn.Value = cols(iN); end
            lblTTInfo.Text = sprintf('Geladen: %s', full);
            updateComparison();

            btnCmpRun.Enable = 'on';  % TT ist da -> erlauben

        catch ME
            uialert(gcbf,"Fehler beim Laden: "+ME.message,'Messdatei');
        end
    end

    function [tMeas, y] = getMeasSeries(varName)
        tMeas = []; y = [];
        if isempty(TT_meas), return; end
        try
            ts = TT_meas.Properties.RowTimes;
            t0 = seconds(ts - ts(1));
            if ismember(varName, string(TT_meas.Properties.VariableNames))
                y = toDouble_local(TT_meas.(varName));
                tMeas = double(t0);
            end
        catch
            tMeas = []; y = [];
        end
    end

    % --- Auswertung: Geschwindigkeit (aus OCR-Processing) ---
    function [tEvalV, vEvalV] = getEvalSpeed()
        [tEvalV, vEvalV] = getSeriesFromTnew_local({'v_Fzg_kmph','v_kmh','v_km_h','speed_kmh'});
        if isempty(tEvalV)
            [tEvalV, vEvalV] = getSeriesFromProcessed_local({'v_Fzg_kmph','v_kmh','v_km_h','speed_kmh'});
        end
    end

    % --- Auswertung: Drehzahl (bevorzugt Audio, sonst OCR) ---
    function [tEvalN, nEval] = getEvalRPM()
        tEvalN=[]; nEval=[];
        try
            if isfield(recordResult,'audio_rpm')
                ar = recordResult.audio_rpm.processed;   % enthält t_s_spec & rpm_final aus deiner Audioanalyse
                tEvalN = double(ar.t_s_spec(:));
                nEval  = double(ar.rpm_final(:));
                return;
            end
        catch
        end
        [tEvalN, nEval] = getSeriesFromTnew_local({'n_mot_Upmin','rpm','n_mot'});
        if isempty(tEvalN)
            [tEvalN, nEval] = getSeriesFromProcessed_local({'n_mot_Upmin','rpm','n_mot'});
        end
    end

    function updateComparison()
        cla(axCmpV); cla(axCmpN);
        ao = sldOff.Value;
        xWin = [sldStart.Value, sldEnd.Value] + ao;
    
        % --- Init ---
        % maeV = NaN; medV = NaN; maxV = NaN; vHit = 0; vTot = 0; vPct = NaN;
        % maeN = NaN; medN = NaN; maxN = NaN; nHit = 0; nTot = 0; nPct = NaN;
    
        %% ---------- Geschwindigkeit (nur TT ↔ OCR) ----------
        vHit=0; vTot=0; vPct=NaN; maeV=NaN; medV=NaN; maxV=NaN;
        haveOCRv=false; haveTTv=false;
        
        % OCR v (gewählte Spalte)
        [tOCRv, vOCR] = deal([],[]);
        if exist('ddOCRv','var') && ddOCRv.Enable=="on" && ~isempty(ddOCRv.Value)
            [tOCRv, vOCR] = getSeriesFromOCRvar(string(ddOCRv.Value));
            if ~isempty(tOCRv)
                haveOCRv = true;
                plot(axCmpV, tOCRv+ao, vOCR, 'LineWidth',1.2); hold(axCmpV,'on');  % "OCR (gewählt)"
            end
        end
        
        % TT v
        if ~isempty(TT_meas) && ddTTv.Enable=="on" && ~isempty(ddTTv.Value)
            [tTTv, vTT] = getMeasSeries(ddTTv.Value);
            if ~isempty(tTTv)
                haveTTv = true;
                tTTv = tTTv + sldCmpOff.Value;
                plot(axCmpV, tTTv, vTT, '--', 'LineWidth',1.0);                    % "Messdatei"
            end
        end
        
        % Metrik: immer OCR (gewählt) ↔ Messdatei
        if haveOCRv && haveTTv
            [maeV, medV, maxV, vHit, vTot] = metrics_abs(tOCRv+ao, vOCR, tTTv, vTT, double(edtTolV.Value));
            if vTot>0, vPct = 100*vHit/vTot; end
        end
        
        xlim(axCmpV, xWin); ylabel(axCmpV,'km/h'); grid(axCmpV,'on');
        if haveOCRv && haveTTv
            legend(axCmpV,{'OCR (gewählt)','Messdatei'},'Location','best');
        elseif haveOCRv
            legend(axCmpV,{'OCR (gewählt)'},'Location','best');
        elseif haveTTv
            legend(axCmpV,{'Messdatei'},'Location','best');
        end
        
        if isfinite(vPct)
            title(axCmpV, sprintf('Geschwindigkeit — Treffer: %.1f%% (%d/%d)  |  Tol ≤ %.1f km/h', ...
                vPct, vHit, vTot, double(edtTolV.Value)));
        end
    
        %% ---------- Drehzahl ----------
        [tAudio, nAudio] = getEvalRPM();     % Audio (final)
        haveAudio = ~isempty(tAudio);
        if haveAudio
            plot(axCmpN, tAudio+ao, nAudio, 'LineWidth',1.2); hold(axCmpN,'on');
        end
        
        % TT n
        haveTTn=false; nHitTT=0; nTotTT=0; nPctTT=NaN;
        if ~isempty(TT_meas) && ddTTn.Enable=="on" && ~isempty(ddTTn.Value)
            [tTTn, nTT] = getMeasSeries(ddTTn.Value);
            if ~isempty(tTTn)
                haveTTn=true;
                tTTn = tTTn + sldCmpOff.Value;
                plot(axCmpN, tTTn, nTT, '--', 'LineWidth',1.0);
                if haveAudio
                    [~, ~, ~, nHitTT, nTotTT] = metrics_abs(tAudio+ao, nAudio, tTTn, nTT, double(edtTolN.Value));
                    if nTotTT>0, nPctTT = 100*nHitTT/nTotTT; end
                end
            end
        end
        
        % OCR n (optional via Checkbox)
        haveOCRn=false; nHitOCR=0; nTotOCR=0; nPctOCR=NaN;
        if exist('cbUseOCRn','var') && cbUseOCRn.Value && exist('ddOCRn','var') && ddOCRn.Enable=="on" && ~isempty(ddOCRn.Value)
            [tOCRn, nOCR] = getSeriesFromOCRvar(string(ddOCRn.Value));
            if ~isempty(tOCRn)
                haveOCRn=true;
                plot(axCmpN, tOCRn+ao, nOCR, ':', 'LineWidth',1.0);
                if haveAudio
                    [~, ~, ~, nHitOCR, nTotOCR] = metrics_abs(tAudio+ao, nAudio, tOCRn+ao, nOCR, double(edtTolN.Value));
                    if nTotOCR>0, nPctOCR = 100*nHitOCR/nTotOCR; end
                end
            end
        end
        
        xlim(axCmpN, xWin); ylabel(axCmpN,'1/min'); grid(axCmpN,'on');
        
        lg = {};
        if haveAudio, lg{end+1}='Audio (final)'; end
        if haveTTn,   lg{end+1}='Messdatei';     end
        if haveOCRn,  lg{end+1}='OCR (gewählt)'; end
        if ~isempty(lg), legend(axCmpN,lg,'Location','best'); end
        
        % Titel: beide Treffer sichtbar
        txtTT  = iff(isfinite(nPctTT),  sprintf('Audio↔TT: %.1f%% (%d/%d)',  nPctTT,  nHitTT,  nTotTT),  'Audio↔TT: —');
        txtOCR = iff(isfinite(nPctOCR), sprintf('Audio↔OCR: %.1f%% (%d/%d)', nPctOCR, nHitOCR, nTotOCR), 'Audio↔OCR: —');
        title(axCmpN, "Drehzahl — " + txtTT + "   |   " + txtOCR + sprintf('   |   Tol ≤ %.0f rpm', double(edtTolN.Value)));

        %% Statuszeile
        lblHit.Text = sprintf('Treffer v (OCR↔TT): %s   |   %s   |   %s', ...
            iff(isfinite(vPct), sprintf('%.1f%% (%d/%d)', vPct, vHit, vTot), '—'), ...
            txtTT, txtOCR);
            % txtTT(9:end), txtOCR(9:end));

        %% Ergebnis speichern

        % ==== VALIDATION SPEICHERN (am Ende von updateComparison) ====
        
        % --- Labels/Bezeichnungen robust abfragen ---
        try label_TT_v  = string(ddTTv.Value);  catch, label_TT_v  = ""; end
        try label_TT_n  = string(ddTTn.Value);  catch, label_TT_n  = ""; end
        try label_OCR_v = string(ddOCRv.Value); catch, label_OCR_v = "OCR (v)"; end
        
        % OCR-n Label NUR speichern, wenn Checkbox aktiv ist
        % use_ocr_n = false;
        try
            use_ocr_n = logical(cbUseOCRn.Value);
        catch
            use_ocr_n = false;
        end
        if use_ocr_n && exist('ddOCRn','var') && ddOCRn.Enable=="on" && ~isempty(ddOCRn.Value)
            label_OCR_n = string(ddOCRn.Value);
        else
            label_OCR_n = "";   % leer lassen, wenn nicht verwendet
        end
        
        % --- Zeit-Offsets / Bezug ---
        try offset_global = double(sldOff.Value); catch, try offset_global = double(ao); catch, offset_global = NaN; end; end
        try offset_cmp    = double(sldCmpOff.Value); catch, offset_cmp = NaN; end
        
        try
            if strcmpi(string(ddTTv.Enable),"on") && ~isempty(ddTTv.Value)
                ref_v = "TT";
            else
                ref_v = "OCR";
            end
        catch
            ref_v = "OCR"; 
        end
        try
            if strcmpi(string(ddTTn.Enable),"on") && ~isempty(ddTTn.Value)
                ref_n = "TT";
            else
                ref_n = "OCR";
            end
        catch 
            ref_n = "OCR"; 
        end
        
        % --- Fullpath zur Referenz-MAT-Datei ---
        tt_mat_fullpath = "";
        % 1) Primär: aus Label "Geladen: <pfad>" extrahieren
        try
            if exist('lblTTInfo','var')
                infoTxt = string(lblTTInfo.Text);
                if startsWith(infoTxt,"Geladen: ")
                    tt_mat_fullpath = string(strtrim(extractAfter(infoTxt,'Geladen: ')));
                end
            end
        catch
            % ignorieren
        end
        % 2) Fallbacks aus möglichen Variablen
        if tt_mat_fullpath == ""
            try
                if exist('TT_path','var') && ~isempty(TT_path),                 tt_mat_fullpath = string(TT_path);       end
                if exist('ttFilePath','var') && ~isempty(ttFilePath),           tt_mat_fullpath = string(ttFilePath);    end
                if exist('measMatFullPath','var') && ~isempty(measMatFullPath), tt_mat_fullpath = string(measMatFullPath); end
                if exist('fileTT','var') && ~isempty(fileTT),                   tt_mat_fullpath = string(fileTT);        end
            catch
                % leer lassen, wenn nichts greift
            end
        end
        
        % --- Ergebnisse übernehmen ---
        validation = struct();
        validation.results = struct( ...
            'comparison_accuracy_v',      vPct,    ...   % Geschwindigkeit (% Treffer)
            'comparison_accuracy_n_TT',   nPctTT,  ...   % Drehzahl ggü. TT
            'comparison_accuracy_n_OCR',  nPctOCR  ...   % Drehzahl ggü. OCR
            );
        
        validation.params = struct( ...
            'tol_v',              double(edtTolV.Value), ...
            'tol_n',              double(edtTolN.Value), ...
            'label_TT_v',         label_TT_v, ...
            'label_TT_n',         label_TT_n, ...
            'label_OCR_v',        label_OCR_v, ...
            'label_OCR_n',        label_OCR_n, ...      % nur gesetzt, wenn Checkbox aktiv
            'use_ocr_n',          logical(use_ocr_n), ...% Checkbox-Status mit speichern
            'time_offset_global', offset_global, ...
            'time_offset_cmp',    offset_cmp, ...
            'reference_v',        string(ref_v), ...
            'reference_n',        string(ref_n), ...
            'tt_mat_fullpath',    tt_mat_fullpath ...
            );
        
        % In recordResult ablegen
        if ~isfield(recordResult, 'validation')
            recordResult.validation = struct();
        end
        recordResult.validation = validation;
        
        % In die MAT-Datei schreiben (filePath muss zuvor gesetzt worden sein)
        try
            save(filePath, 'recordResult', '-v7.3');
        catch saveErr
            warning(saveErr.identifier, 'Konnte validation nicht speichern: %s', saveErr.message);
        end
        % ==== /VALIDATION SPEICHERN ====



    end



    % --------- lokale Minimal-Helper (unabhängig von Tab 2) ----------
    function [tser, yser] = getSeriesFromTnew_local(cands)
        tser=[]; yser=[];
        try
            if exist('T_new','var') && istable(T_new) && ismember('t_s',T_new.Properties.VariableNames)
                tser = double(T_new.t_s(:));
                for i=1:numel(cands)
                    nm=cands{i};
                    if ismember(nm,T_new.Properties.VariableNames) && ~all(ismissing(T_new.(nm)))
                        yser = toDouble_local(T_new.(nm)(:)); return
                    end
                end
            end
        catch
            tser=[]; yser=[];
        end
    end

    function [tser, yser] = getSeriesFromProcessed_local(cands)
        tser=[]; yser=[];
        try
            if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'processed') && istable(recordResult.ocr.processed)
                P = recordResult.ocr.processed;
                if ismember('t_s',P.Properties.VariableNames)
                    tser = double(P.t_s(:));
                    for i=1:numel(cands)
                        nm=cands{i};
                        if ismember(nm,P.Properties.VariableNames) && ~all(ismissing(P.(nm)))
                            yser = toDouble_local(P.(nm)(:)); return
                        end
                    end
                end
            end
        catch
            tser=[]; yser=[];
        end
    end

    function x = toDouble_local(col)
        if isnumeric(col), x=double(col); return; end
        if iscell(col)
            try
                x = str2double(string(col)); return
            catch
            end
        end
        if isstring(col) || iscategorical(col)
            try
                x = str2double(string(col)); return;
            catch
            end
        end
        x = double(col);  % letzter Versuch (wirft ggf.)
    end

    % === Neue Helper: absolute Vergleichsmetriken ===
    function [mae, medae, maxae, nHit, nTot] = metrics_abs(tRef, yRef, tCmp, yCmp, tolAbs)
        mae = NaN; medae = NaN; maxae = NaN; nHit = 0; nTot = 0;
        if isempty(tRef) || isempty(yRef) || isempty(tCmp) || isempty(yCmp), return; end
        % Fenster wie bisher:
        ao = sldOff.Value; xWin = [sldStart.Value, sldEnd.Value] + ao;
        m = isfinite(yRef) & tRef>=xWin(1) & tRef<=xWin(2);
        if ~any(m), return; end
        tR = tRef(m); yR = yRef(m);
        yCi = interp1(tCmp, yCmp, tR, 'linear', 'extrap');
        good = isfinite(yR) & isfinite(yCi);
        if ~any(good), return; end
        d = abs(yR(good) - yCi(good));
        mae   = mean(d);
        medae = median(d);
        maxae = max(d);
        nTot  = numel(d);
        nHit  = nnz(d <= tolAbs);
    end

    % === Helper: sofort speichern + Vergleich refreshen ===
    function reanalyzeAndSave()
        try
            onRunRPM2();  % baut Spektrogramm/RPM/v/Gang neu und speichert audio_rpm
            % Vergleichs-Tab direkt mitziehen:
            try
                fUpd = getappdata(fig,'fnUpdateComparison');
                if isa(fUpd,'function_handle'), fUpd(); end
            catch
            end
        catch ME
            warning(ME.identifier, 'Auto-Neuanalyse fehlgeschlagen: %s', ME.message);
        end
    end

    function populateOCRDropdowns()
        itemsAll = string([]);
        try
            Tsrc = [];
            if isfield(recordResult,'ocr')
                if isfield(recordResult.ocr,'processed') && istable(recordResult.ocr.processed)
                    Tsrc = recordResult.ocr.processed;
                elseif isfield(recordResult.ocr,'table') && istable(recordResult.ocr.table)
                    Tsrc = recordResult.ocr.table;
                end
            end
            if ~isempty(Tsrc)
                cols = string(Tsrc.Properties.VariableNames);
                itemsAll = cols(~ismember(cols, ["t_s","nr_frame","frame_idx"]));
            end
        catch
            itemsAll = string([]);
        end
    
        % v: alle erlauben
        if ~isempty(itemsAll)
            ddOCRv.Items = itemsAll; ddOCRv.Enable = 'on';
            if isempty(ddOCRv.Value) || ~any(itemsAll==ddOCRv.Value), ddOCRv.Value = itemsAll(1); end
        else
            ddOCRv.Items = {}; ddOCRv.Enable = 'off';
        end
    
        % n: alle erlauben (Vorauswahl nach Heuristik)
        if ~isempty(itemsAll)
            ddOCRn.Items = itemsAll; ddOCRn.Enable = 'on';
            pickN = find(contains(lower(itemsAll),["rpm","n_mot","engine"]),1);
            if ~isempty(pickN), ddOCRn.Value = itemsAll(pickN);
            elseif isempty(ddOCRn.Value) || ~any(itemsAll==ddOCRn.Value)
                ddOCRn.Value = itemsAll(1);
            end
            cbUseOCRn.Enable = 'on';
        else
            ddOCRn.Items = {}; ddOCRn.Enable = 'off';
            cbUseOCRn.Value = false; cbUseOCRn.Enable = 'off';
        end
    end


    function [tser, yser] = getSeriesFromOCRvar(varName)
        tser = []; yser = [];
        if isempty(varName), return; end
        try
            % Priorität: processed -> table
            if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'processed') && istable(recordResult.ocr.processed)
                P = recordResult.ocr.processed;
                if ismember('t_s', P.Properties.VariableNames) && ismember(varName, P.Properties.VariableNames)
                    tser = double(P.t_s(:));
                    yser = toDouble_local(P.(varName)(:));
                    return
                end
            end
            if isfield(recordResult,'ocr') && isfield(recordResult.ocr,'table') && istable(recordResult.ocr.table)
                T = recordResult.ocr.table;
                if ismember('t_s', T.Properties.VariableNames) && ismember(varName, T.Properties.VariableNames)
                    tser = double(T.t_s(:));
                    yser = toDouble_local(T.(varName)(:));
                    return
                end
            end
        catch
            tser = []; yser = [];
        end
    end

    function ok = restoreCmpFromValidation()
        ok = false;
    
        % Muss existieren, weil du recordResult bereits ganz am Anfang aus der
        % gewählten results_*.mat geladen hast.
        if ~exist('recordResult','var') || ~isfield(recordResult,'validation') ...
                || ~isfield(recordResult.validation,'params')
            return;
        end
    
        P = recordResult.validation.params;
    
        % ==== 1) Mess-TT aus Pfad laden (falls vorhanden) ====
        tt_mat_fullpath = "";
        if isfield(P,'tt_mat_fullpath') && strlength(string(P.tt_mat_fullpath))>0
            tt_mat_fullpath = string(P.tt_mat_fullpath);
        end
        if tt_mat_fullpath ~= "" && isfile(tt_mat_fullpath)
            try
                L = load(tt_mat_fullpath,'TT');
                if isfield(L,'TT') && istimetable(L.TT)
                    TT_meas = L.TT;                     
                    assignin('caller','TT_meas',TT_meas);
    
                    % Dropdowns vorbereiten
                    cols = string(TT_meas.Properties.VariableNames);
                    ddTTv.Items = cols; ddTTn.Items = cols;
                    ddTTv.Enable = 'on'; ddTTn.Enable = 'on';
    
                    % Vorauswahl aus params
                    if isfield(P,'label_TT_v') && any(cols==string(P.label_TT_v))
                        ddTTv.Value = string(P.label_TT_v);
                    end
                    if isfield(P,'label_TT_n') && any(cols==string(P.label_TT_n))
                        ddTTn.Value = string(P.label_TT_n);
                    end
    
                    % Infozeile aktualisieren
                    try
                        lblTTInfo.Text = sprintf('Geladen: %s', tt_mat_fullpath);
                    catch
                    end
    
                    btnCmpRun.Enable = 'on';
                end
            catch ME
                warning(ME.identifier, 'TT aus validation.params konnte nicht geladen werden: %s', ME.message);
            end
        end
    
        % ==== 2) OCR-Dropdowns aus OCR-Daten bestücken ====
        try
            % Quelle bestimmen (processed bevorzugen)
            Tsrc = [];
            if isfield(recordResult,'ocr')
                if isfield(recordResult.ocr,'processed') && istable(recordResult.ocr.processed)
                    Tsrc = recordResult.ocr.processed;
                elseif isfield(recordResult.ocr,'table') && istable(recordResult.ocr.table)
                    Tsrc = recordResult.ocr.table;
                end
            end
            if ~isempty(Tsrc)
                cols = string(Tsrc.Properties.VariableNames);
    
                % v
                ddOCRv.Items = cols; ddOCRv.Enable = 'on';
                if isfield(P,'label_OCR_v') && any(cols==string(P.label_OCR_v))
                    ddOCRv.Value = string(P.label_OCR_v);
                else
                    % Heuristik: erste passende Spalte wählen
                    candV = cols(contains(lower(cols), ["v_fzg","kmh","km_h","speed"]));
                    if ~isempty(candV), ddOCRv.Value = candV(1); end
                end
    
                % n
                ddOCRn.Items = cols; ddOCRn.Enable = 'on';
                if isfield(P,'label_OCR_n') && strlength(string(P.label_OCR_n))>0 ...
                        && any(cols==string(P.label_OCR_n))
                    ddOCRn.Value = string(P.label_OCR_n);
                else
                    candN = cols(contains(lower(cols), ["n_mot","rpm"]));
                    if ~isempty(candN), ddOCRn.Value = candN(1); end
                end
    
                % Checkbox „OCR-RPM verwenden“
                if isfield(P,'use_ocr_n')
                    cbUseOCRn.Value = logical(P.use_ocr_n);
                end
                cbUseOCRn.Enable = 'on';
            end
        catch
        end
    
        % ==== 3) Toleranzen, Referenzen, Offsets aus params ====
        try if isfield(P,'tol_v'),   edtTolV.Value   = double(P.tol_v);   end; catch, end
        try if isfield(P,'tol_n'),   edtTolN.Value   = double(P.tol_n);   end; catch, end
        try if isfield(P,'ref_v'),   ddRefV.Value    = string(P.ref_v);   end; catch, end
        try if isfield(P,'ref_n'),   ddRefN.Value    = string(P.ref_n);   end; catch, end
        try
            if isfield(P,'time_offset_cmp')
                sldCmpOff.Value = double(P.time_offset_cmp);
                lblCmpOff.Text  = sprintf('%.2f s', double(P.time_offset_cmp));
            end
        catch
        end
    
        % Hinweis: Der globale Audio-Offset (time_offset_global) wird in Tab 2
        % verwaltet (sldOff). Wenn du den ebenfalls wiederherstellen willst:
        try
            if isfield(P,'time_offset_global') && isfinite(double(P.time_offset_global))
                sldOff.Value = double(P.time_offset_global);
                updateOffset(double(P.time_offset_global));  % verschiebt visuelle Overlays
            end
        catch
        end
    
        % ==== 4) Vergleich einmalig aktualisieren ====
        try
            updateComparison();
        catch
        end
    
        ok = true;
    end
    
    function R = checkTimeRun(time_s, t_s)
    %CHECKTIMERUN Prüft, ob OCR-Zeit t_s den gleichen Lauf hat wie time_s.
    % Eingaben:
    %   time_s : Nx1 reale Videozeit [s]
    %   t_s    : Nx1 OCR-zeit [s]
    %   opts   : (optional) Struktur mit Feldern:
    %            .slopeTol        (default 0.01)   -> |b-1| max
    %            .rmsTol          (default 0.05)   -> RMS-Residual [s]
    %            .stepAbsTol      (default 0.10)   -> |diff-Fehler| [s]
    %            .stepMadK        (default 6)      -> k * MAD-Schwelle
    %            .minStep         (default 1e-6)   -> zur Division/Ratio-Schutz
    %
    % Rückgabe R: Struktur mit
    %   .ok                : Gesamt-Gut/Schlecht (bool)
    %   .ok_slope, .ok_rms : Teilkriterien (bool)
    %   .slope, .intercept : b, a aus linearer Regression
    %   .r2, .rms          : Gütemaße
    %   .stepErr           : diff(t_s) - diff(time_s)
    %   .jumpIdx           : Indizes (im diff-Sinn) auffälliger Sprünge
    %   .nonmonoIdx        : Indizes, an denen t_s nicht monoton steigt
    %   .badIdx            : Vereinigung aller Problemstellen (als Stichprobe)
    %
    % Hinweis: NaNs werden ignoriert.

        opts.slopeTol   = 0.01;
        opts.rmsTol     = 0.05;
        opts.stepAbsTol = 0.10;
        opts.stepMadK   = 6;
        opts.minStep    = 1e-6;
    
        % gemeinsame gültige Indizes
        I = ~(isnan(time_s) | isnan(t_s));
        x = time_s(I); 
        x_alt = t_s(I);
        N = numel(x);
    
        % Defaults falls zu wenige Punkte
        R = struct('ok',false,'ok_slope',false,'ok_rms',false, ...
                   'slope',NaN,'intercept',NaN,'r2',NaN,'rms',NaN, ...
                   'stepErr',[], 'jumpIdx',[], 'nonmonoIdx',[], 'badIdx',[]);
        if N < 3
            return
        end
    
        % Lineare Regression y ≈ a + b*x
        p = polyfit(x, x_alt, 1);  % [b a]
        b = p(1); a = p(2);
        yhat = polyval(p, x);
        resid = x_alt - yhat;
        R.slope = b; R.intercept = a;
    
        % Gütemaße
        ss_res = sum(resid.^2);
        ss_tot = sum( (x_alt - mean(x_alt)).^2 );
        R.r2  = 1 - ss_res/max(ss_tot, eps);
        R.rms = sqrt(mean(resid.^2));
    
        % Schritt-Konsistenz und Sprungerkennung
        dx = diff(x);
        dy = diff(x_alt);
        stepErr = dy - dx;             % idealerweise ~ 0
        R.stepErr = stepErr;
    
        % Monotonie-Verletzungen in t_s (sollte i.d.R. nicht fallen)
        R.nonmonoIdx = find(dy < -opts.minStep);
    
        % robuste MAD-Schwelle + absoluter Toleranzboden
        med = median(stepErr, 'omitnan');
        madv = mad(stepErr, 1);        % median absolute deviation (L1)
        thr = max(opts.stepAbsTol, opts.stepMadK * max(madv, eps));
        R.jumpIdx = find(abs(stepErr - med) > thr);
    
        % Kriterien
        R.ok_slope = abs(b - 1) <= opts.slopeTol;
        R.ok_rms   = R.rms <= opts.rmsTol;
        R.ok       = R.ok_slope && R.ok_rms && isempty(R.jumpIdx) && isempty(R.nonmonoIdx);
    
        % "bad" Beispielstellen (Indices im Originalsignal-Bereich 1..N)
        badDiffIdx = unique([R.jumpIdx(:); R.nonmonoIdx(:)]);
        badSampleIdx = unique([badDiffIdx; badDiffIdx+1]);        % auf Samples heben
        badSampleIdx(badSampleIdx < 1 | badSampleIdx > N) = [];
        % zurück auf Originalindizes
        origIdx = find(I);
        R.badIdx = origIdx( badSampleIdx );
    end
end
