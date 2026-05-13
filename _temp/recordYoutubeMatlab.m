function recordYoutubeMatlab(youtubeURL, ifExistThenSkip, buildIndex)

%% === Run YouTube Recorder (Python script) from MATLAB ===
% Pfade anpassen

currentDir = pwd;
venvPython = fullfile(currentDir, "python\.venv\Scripts\python.exe");
scriptPath = fullfile(currentDir, "python\record_youtube_cfr.py");
captureRoot = fullfile(currentDir, "captures");
resultsRoot = fullfile(currentDir, "results");

% URL
% youtubeURL = "https://www.youtube.com/watch?v=s2HPIhCog6s"; % Audi RS 3 2024
% youtubeURL = "https://www.youtube.com/watch?v=PQmSUHhP3ug"; % Porsche 919
% youtubeURL = "https://www.youtube.com/watch?v=s2HPIhCog6s"; % Audi RS3 2024
% youtubeURL = "https://www.youtube.com/watch?v=ATd4mFgBkw0"; % BMW M2 CS
% youtubeURL = "https://www.youtube.com/watch?v=CrYXIl6YS3g"; % VW Golf GTI Edition 50
% youtubeURL = "https://www.youtube.com/watch?v=td_c1zeEn2Q"; % BYD U9 Xtreme 02
% youtubeURL = "https://www.youtube.com/watch?v=ATd4mFgBkw0"; % BMW M2 CS
% youtubeURL = "https://www.youtube.com/watch?v=-rLUdBVYIlg"; % VW Golf GTI Clubsport S
% youtubeURL = "https://www.youtube.com/watch?v=2PuFyjAs7JA"; % short video test;

% Aufnahme-Parameter
durationSec = 9999;   % SOVIEL Sekunden mindestens aufnehmen
fps         = 30;     % 30 oder 60

tstamp  = string(datetime('now','Format','yyyyMMdd_HHmmss'));
outBase = "screen_" + tstamp;               % passt zu deiner Save-Logik
outDir  = fullfile(captureRoot, tstamp);    % z.B. ...\captures\20251104_141530

if ~isfolder(resultsRoot); mkdir(resultsRoot); end

%% === (NEU) Vorab: Dubletten-Check im results-Ordner anhand der URL / Video-ID
curID = getVideoId(youtubeURL);
[dupCountURL, dupListURL] = findExistingByURL(resultsRoot, curID);

if dupCountURL > 0
    msg = composeDupMsg("Dieses Video (per URL/ID) wurde bereits heruntergeladen.", dupListURL);

    if ~ifExistThenSkip
        choice = questdlg(msg, 'Bereits vorhanden', 'Ja, trotzdem aufnehmen', 'Nein, abbrechen', 'Nein, abbrechen');
    else
        choice = 'Nein, abbrechen';
    end

    if ~strcmp(choice, 'Ja, trotzdem aufnehmen')
        disp('Abbruch, da bereits vorhandener Download erkannt wurde.');

        if buildIndex
            buildIndexAndLog(resultsRoot);
        end
        return;
    end
end

% Erst einen Ordner erstellen wenn kein Abbruch
if ~isfolder(outDir); mkdir(outDir); end

%% --- Python-Interpreter in MATLAB aktivieren
if ~strcmp(pyenv().Version, venvPython)
    disp("Setting MATLAB Python environment to virtualenv...");
    pyenv('Version', venvPython);
end
disp("Using Python interpreter: " + string(pyenv().Version));

%% --- Unbuffered (-u) + Argumente (URL, Dauer, Out, FPS)
psi = System.Diagnostics.ProcessStartInfo;
psi.FileName = venvPython;
psi.Arguments = sprintf('-u "%s" --url "%s" --duration %.3f --out "%s" --fps %.2f --outdir "%s"', ...
    scriptPath, youtubeURL, durationSec, outBase, fps, outDir);

psi.UseShellExecute = false;
psi.RedirectStandardOutput = true;
psi.RedirectStandardError = true;
psi.CreateNoWindow = true;
psi.StandardOutputEncoding = System.Text.Encoding.UTF8;
psi.StandardErrorEncoding  = System.Text.Encoding.UTF8;

process   = System.Diagnostics.Process.Start(psi);
reader    = process.StandardOutput;
errReader = process.StandardError;

videoFile = "";
audioFile = "";
videoTitle = "";
videoURL  = "";   % vom Python-Script geliefert (RESULT_URL)
videoDesc = "";
videoPubDate = "";
videoChanName = "";

disp("=== Python Output ===");
while ~reader.EndOfStream
    line = char(reader.ReadLine());
    if ~isempty(line); disp(line); end
    drawnow limitrate;

    if startsWith(line, "RESULT_VIDEO:")
        videoFile = strtrim(erase(line, "RESULT_VIDEO:"));
    elseif startsWith(line, "RESULT_AUDIO:")
        audioFile = strtrim(erase(line, "RESULT_AUDIO:"));
    elseif startsWith(line, "RESULT_TITLE:")
        videoTitle = strtrim(erase(line, "RESULT_TITLE:"));
    elseif startsWith(line, "RESULT_URL:")
        videoURL = strtrim(erase(line, "RESULT_URL:"));
    elseif startsWith(line, "RESULT_DESC:")
        videoDesc = strtrim(erase(line, "RESULT_DESC:"));
    elseif startsWith(line, "RESULT_PUBDATE:")
        videoPubDate = strtrim(erase(line, "RESULT_PUBDATE:"));
    elseif startsWith(line, "RESULT_CHANNAME:")
        videoChanName = strtrim(erase(line, "RESULT_CHANNAME:"));
    end
    
end

while ~errReader.EndOfStream
    disp("[stderr] " + char(errReader.ReadLine()));
    drawnow limitrate;
end

process.WaitForExit();
disp("=== Python Finished ===");
fprintf("Title: %s\n", videoTitle);
fprintf("Video file: %s\n", videoFile);
fprintf("Audio file: %s\n", audioFile);
fprintf("URL: %s\n", videoURL);
fprintf("Description: %s\n", videoDesc);
fprintf("Publish Date: %s\n", videoPubDate);
fprintf("Channel Name: %s\n", videoChanName);

%% === (NEU) Nachträglicher Dubletten-Check per Titel (vor dem Speichern)
% Falls aus historischen MAT-Dateien keine URL vorlag, verhindert das doppelte Saves.
if ~isempty(videoTitle)
    [dupCountTitle, dupListTitle] = findExistingByTitle(resultsRoot, videoTitle);
    if dupCountTitle > 0
        msg = composeDupMsg("Ein Eintrag mit demselben Titel existiert bereits.", dupListTitle);
        choice = questdlg(msg, 'Doppelter Titel', 'Trotzdem speichern', 'Nicht speichern', 'Nicht speichern');
        if ~strcmp(choice, 'Trotzdem speichern')
            % Optional: aufräumen, wenn man gar nichts behalten will
            try
                if ~isempty(videoFile) && isfile(videoFile); delete(videoFile); end
                if ~isempty(audioFile) && isfile(audioFile); delete(audioFile); end
                if isfolder(outDir) && isempty(dir(fullfile(outDir,'*'))); rmdir(outDir); end
            catch ME
                warning(ME.identifier, 'Aufräumen fehlgeschlagen: %s', ME.message);
            end
            disp('Abbruch ohne Speichern (Titel-Duplikat).');
            buildIndexAndLog(resultsRoot);   % <— NEU: Index trotzdem erstellen
            return;
        end
    end
end

%% === Save results_*.mat

metadata = struct();

metadata.title      = videoTitle;
metadata.video      = videoFile;
metadata.audio      = audioFile;
metadata.url        = iff(~isempty(videoURL), videoURL, youtubeURL);  % Fallback
metadata.created_at = datetime('now');
metadata.outdir     = outDir;
metadata.fps        = fps;
metadata.duration   = durationSec;
metadata.pubDate    = videoPubDate;
metadata.desc       = videoDesc;
metadata.chanName   = videoChanName;

recordResult.metadata = metadata;

assignin("base", "recordResult", recordResult);
disp("Result stored in variable 'recordResult'.");

resultsMat = fullfile(resultsRoot, "results_" + tstamp + ".mat");
save(resultsMat, "recordResult");
fprintf("Ergebnis gespeichert: %s\n", resultsMat);
buildIndexAndLog(resultsRoot);           % <— Index immer zuletzt neu bauen

%% =======================
%%        Helpers
%% =======================
function id = getVideoId(u)
% Extrahiert die 11-stellige YouTube Video-ID aus unterschiedlichen URL-Formen.
% Unterstützt: watch?v=ID, youtu.be/ID, embed/ID, shorts/ID
    id = "";
    if isempty(u); return; end
    u = char(string(u));
    % 1) watch?v=ID
    m = regexp(u, '[?&]v=([A-Za-z0-9_\-]{11})', 'tokens', 'once');
    if ~isempty(m); id = string(m{1}); return; end
    % 2) youtu.be/ID
    m = regexp(u, 'youtu\.be/([A-Za-z0-9_\-]{11})', 'tokens', 'once');
    if ~isempty(m); id = string(m{1}); return; end
    % 3) /embed/ID
    m = regexp(u, '/embed/([A-Za-z0-9_\-]{11})', 'tokens', 'once');
    if ~isempty(m); id = string(m{1}); return; end
    % 4) /shorts/ID
    m = regexp(u, '/shorts/([A-Za-z0-9_\-]{11})', 'tokens', 'once');
    if ~isempty(m); id = string(m{1}); return; end
end

function [count, hitList] = findExistingByURL(resultsRoot, curID)
% Sucht in results_*.mat nach gleicher Video-ID (recordResult.url)
    count = 0; hitList = strings(0,1);
    if strlength(curID)==0 || ~isfolder(resultsRoot); return; end
    D = dir(fullfile(resultsRoot, 'results_*.mat'));
    for k = 1:numel(D)
        f = fullfile(D(k).folder, D(k).name);
        try
            S = load(f, 'recordResult');
            if ~isfield(S, 'recordResult'); continue; end
            RR = S.recordResult.metadata;
            if ~isstruct(RR); continue; end
            if isfield(RR,'url') && ~isempty(RR.url)
                oldID = getVideoId(string(RR.url));
                if strlength(oldID)>0 && strcmpi(oldID, curID)
                    count = count + 1;
                    hitList(end+1) = formatHit(RR, f); %#ok<AGROW>
                end
            end
        catch
            % still continue on errors
        end
    end
end

function [count, hitList] = findExistingByTitle(resultsRoot, newTitle)
% Case-insensitive Vergleich des Titels (Trim)
    count = 0; hitList = strings(0,1);
    if strlength(newTitle)==0 || ~isfolder(resultsRoot); return; end
    target = lower(strtrim(string(newTitle)));
    D = dir(fullfile(resultsRoot, 'results_*.mat'));
    for k = 1:numel(D)
        f = fullfile(D(k).folder, D(k).name);
        try
            S = load(f, 'recordResult');
            if ~isfield(S, 'recordResult'); continue; end
            RR = S.recordResult.metadata;
            if ~isstruct(RR); continue; end
            if isfield(RR,'title') && ~isempty(RR.title)
                t = lower(strtrim(string(RR.title)));
                if t == target
                    count = count + 1;
                    hitList(end+1) = formatHit(RR, f); %#ok<AGROW>
                end
            end
        catch
        end
    end
end

function s = formatHit(RR, matPath)
% Hübsche Einzeile für Dialog: Datum — Titel — URL/ID — MAT-Datei
    dt = "";
    if isfield(RR,'created_at') && ~isempty(RR.created_at)
        try dt = datestr(RR.created_at, 'yyyy-mm-dd HH:MM'); catch, dt = ""; end
    end
    ttl = iff(isfield(RR,'title') && ~isempty(RR.title), string(RR.title), "(kein Titel)");
    url = iff(isfield(RR,'url')   && ~isempty(RR.url),   string(RR.url),   "(keine URL)");
    id  = getVideoId(url);
    if strlength(id)>0
        urlPart = "ID=" + id;
    else
        urlPart = url;
    end
    s = sprintf("%s — %s — %s\n%s", dt, ttl, urlPart, matPath);
end

function msg = composeDupMsg(heading, lines)
% Baut den Text für questdlg mit ein paar Treffern (max. 5 anzeigen)
    n = numel(lines);
    maxShow = min(n, 5);
    body = strjoin(cellstr(lines(1:maxShow)), newline);
    more = "";
    if n > maxShow
        more = sprintf("\n… und %d weitere.", n - maxShow);
    end
    msg = sprintf("%s\n\nTreffer: %d\n\n%s%s\n\nNochmal herunterladen?", heading, n, body, more);
end

function y = iff(cond, a, b)
% Inline if
    if cond, y = a; else, y = b; end
end

function buildIndexAndLog(resultsRoot)
    try
        buildResultsIndex(resultsRoot);
    catch ME
        warning(ME.identifier, "Konnte Excel-Index nicht erzeugen: %s", ME.message);
    end
end

function buildResultsIndex(resultsRoot)
    if ~isfolder(resultsRoot)
        error("resultsRoot existiert nicht: %s", resultsRoot);
    end
    D = dir(fullfile(resultsRoot, "results_*.mat"));

    n = numel(D);
    Title  = strings(n,1);
    Link   = strings(n,1);
    OCR_prep = false(n,1);
    OCR    = false(n,1);
    Audio  = false(n,1);
    Valid  = false(n,1);
    HitPct = NaN(n,1);
    Filename = strings(n,1);

    for k = 1:n
        f = fullfile(D(k).folder, D(k).name);
        [Title(k), Link(k), OCR_prep(k), OCR(k), Audio(k), Valid(k), HitPct(k)] = extractRowFromMat(f);
        Filename(k) = D(k).name;
    end

    T = table(Filename, Title, Link, OCR_prep, OCR, Audio, Valid, ...
        'VariableNames', {...
        'filename','title','link','ocr_prep_done','ocr_done','audio_done','validation_done'});

    % ts = string(datetime('now','Format','yyyyMMdd_HHmmss'));
    xlsxPath = fullfile(resultsRoot, "results_index_latest.xlsx");

    if isfile(xlsxPath)
        delete(xlsxPath);
    end
    writetable(T, xlsxPath);

    fprintf("✅ Index erzeugt/aktualisiert: %s\n", xlsxPath);
end

function [title, link, ocrPrepDone, ocrDone, audioDone, validDone, hitPct] = extractRowFromMat(matPath)
    title = ""; link = ""; ocrPrepDone = false; 
    ocrDone = false; audioDone = false; validDone = false; hitPct = NaN;

    S = load(matPath);
    if isfield(S, 'recordResult') && isstruct(S.recordResult)
        RR = S.recordResult;

        if isfield(RR, 'metadata') && isstruct(RR.metadata)
            RR_metadata = RR.metadata;
            title = strtrim(string(safeStr(getfield_if(RR_metadata,'title'))));
            link  = strtrim(string(safeStr(getfield_if(RR_metadata,'url'))));
        else
            title = strtrim(string(safeStr(getfield_if(RR,'title'))));
            link  = strtrim(string(safeStr(getfield_if(RR,'url'))));
        end

        % unter-struct audio_rpm vorhanden -> Audioauswertung gemacht
        audioDone       = isstruct(getfield_if(RR, 'audio_rpm'));
        
        if isfield(RR, "ocr") && ...
                isfield(RR.ocr, "params")

            ocrPrepDone = true;

            resume_from_s = RR.ocr.params.resume_from_s;
            end_s = RR.ocr.params.end_s;
            temp_fps = RR.ocr.params.fps;
            delta_time = end_s - resume_from_s;
            if delta_time > 1/temp_fps
                % OCR muss gestartet/fortgesetzt werden, da die Endzeit
                % noch nicht erreicht wurde
            else 
                % OCR fertig, da kein Zeit übergeblieben ist
                ocrDone = true;
            end
        else
            % Param (ROI, Track usw.) noch nicht festgelegt
        end

        if isfield(RR, 'validation') && isfield(RR.validation, 'params')
            if RR.validation.params.tt_mat_fullpath ~= ""
                % Link zum .mat-Datei vorhanden -> bereits validiert
                validDone = true;
            end
        end
    

        

        
        
    end
end

% ===== Utilities =====
function v = getfield_if(S, name)
    if isstruct(S) && isfield(S, name), v = S.(name); else, v = []; end
end

function out = safeStr(x)
    if isstring(x) || ischar(x), out = string(x); else, out = ""; end
end

end

