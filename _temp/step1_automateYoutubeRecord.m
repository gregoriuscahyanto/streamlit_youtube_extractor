clc;
clearvars;
close all;

debug = false;

%%
% Hole links aus einer .txt-Datei
filename = 'Nordschleife_Youtube_Links.txt';
youtubeURLs = string(readlines(filename)); % Datei zeilenweise als String-Array einlesen
youtubeURLs = youtubeURLs(youtubeURLs ~= ""); % Leere Zeilen entfernen (falls vorhanden)

% Zusätzlich: die alte Liste hinzufügen
youtubeURLs = [youtubeURLs
    "https://www.youtube.com/watch?v=s2HPIhCog6s" % Audi RS3 2024
    "https://www.youtube.com/watch?v=PQmSUHhP3ug" % Porsche 919
    "https://www.youtube.com/watch?v=ATd4mFgBkw0" % BMW M2 CS
    "https://www.youtube.com/watch?v=CrYXIl6YS3g" % VW Golf GTI Edition 50
    "https://www.youtube.com/watch?v=td_c1zeEn2Q" % BYD U9 Xtreme 02
    "https://www.youtube.com/watch?v=-rLUdBVYIlg" % VW Golf GTI Clubsport S
    "https://www.youtube.com/watch?v=vpEjrjLaTxE" % Porsche 911 GT3 RS
    "https://www.youtube.com/watch?v=ic7qpuJtHK4" % Chevrolet Corvette ZR1X
    "https://www.youtube.com/watch?v=d5YUiSxsawY" % Ford Mustang GTD
    "https://www.youtube.com/watch?v=WFHbnglmeUA" % Porsche 911 GT2 RS
    "https://www.youtube.com/watch?v=MRgFe3kqRmY" % Mercedes AMG ONE
    "https://www.youtube.com/watch?v=9kZQnHhf_cQ" % Porsche Carrera GT
    "https://www.youtube.com/watch?v=20oDQHBrWSA" % Chevrolet Corvette ZR1
    "https://www.youtube.com/watch?v=MRgFe3kqRmY"
    "https://www.youtube.com/watch?v=yU0vBY2hKqM"
    "https://www.youtube.com/watch?v=cp-KRcEpQEM"
    "https://www.youtube.com/watch?v=wB_5v-ifM30"
    "https://www.youtube.com/watch?v=d5YUiSxsawY"
    "https://www.youtube.com/watch?v=6lunrK9XiXM"
    "https://www.youtube.com/watch?v=OVni4kUCy6s"
    "https://www.youtube.com/watch?v=3-5TfjXad88"
    "https://www.youtube.com/watch?v=W18PKw-cetY"
    "https://www.youtube.com/watch?v=bS7UxaTv3CE"
    "https://www.youtube.com/watch?v=SF2DYwYhSDs"
    "https://www.youtube.com/watch?v=MZCBz8KZypo"
    "https://www.youtube.com/watch?v=byxvitfAdao"
    "https://www.youtube.com/watch?v=SHmHO5dsZUw"
    "https://www.youtube.com/watch?v=zAbdnwqTfBs"
    "https://www.youtube.com/watch?v=k0JP29DP7kQ"
    "https://www.youtube.com/watch?v=aVbCBCWtuQ4"
    "https://www.youtube.com/watch?v=CtSqZOz3sGs"
    "https://www.youtube.com/watch?v=R4ErMhqVupI"
    "https://www.youtube.com/watch?v=DB9heZoZj6Q"
    "https://www.youtube.com/watch?v=L7oRLhYHfRc"
    "https://www.youtube.com/watch?v=SMaQX7MID5I"
    "https://www.youtube.com/watch?v=_Sdy5xPUvWk"
    "https://www.youtube.com/watch?v=fFEc_-2c4u8"
    "https://www.youtube.com/watch?v=GqVRqARkh8g"
    "https://www.youtube.com/watch?v=PPg_cycTGVY"
    "https://www.youtube.com/watch?v=TdI6JCQkS0g"
    "https://www.youtube.com/watch?v=rMu4YVLkPe4"
    "https://www.youtube.com/watch?v=em4I4V-AvBo"
    "https://www.youtube.com/watch?v=_g4oFOpnsaY"
    "https://www.youtube.com/watch?v=JeDN-EE6aac"
    "https://www.youtube.com/watch?v=P4hc2zN1J8w"
    "https://www.youtube.com/watch?v=PVU52Vhi3lM"
    "https://www.youtube.com/watch?v=l_hbqBxxISY"
    "https://www.youtube.com/watch?v=ZPh9Urh_MhE"
    "https://www.youtube.com/watch?v=hMBL497zPhA"
    ];

% Hole links aus einer .txt-Datei
filename = 'Nordschleife_Youtube_Links_v2.txt';
temp_youtubeURLs = string(readlines(filename)); % Datei zeilenweise als String-Array einlesen
temp_youtubeURLs = temp_youtubeURLs(temp_youtubeURLs ~= ""); % Leere Zeilen entfernen (falls vorhanden)
youtubeURLs = [youtubeURLs
    temp_youtubeURLs];

% Hole nur unique values
youtubeURLs = unique(youtubeURLs);

% debug
if debug
    youtubeURLs =  "https://www.youtube.com/watch?v=C0DPdy98e4c";
end

% resume
ifExistThenSkip = true; % Video bereits heruntergeladen -> automatisch skip ohne User Abfrage
buildIndex = false;     % Keine Erstellung von .xlsx-Datei

for i = 1:height(youtubeURLs)
    youtubeURL = youtubeURLs(i);
    recordYoutubeMatlab(youtubeURL, ifExistThenSkip, buildIndex);

    if i == height(youtubeURLs)
        buildIndex = true;
        recordYoutubeMatlab(youtubeURL, ifExistThenSkip, buildIndex);
    end
end
