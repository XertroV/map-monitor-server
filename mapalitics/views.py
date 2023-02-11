import json
import os
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseNotAllowed, HttpRequest, HttpResponseForbidden, HttpResponse
from django.db.models import Count

from mapalitics.models import MapaliticsToken, TrackEvent, User



def get_ml_script(request: HttpRequest):
    is_demo = 'demo' in request.GET
    return HttpResponse("""
<manialink name="Mapalitics" version="3">

<label id="mapalitics-label" pos="-155 85" hidden="{LABEL_VIS}" z-index="3" textsize="5" halign="left" textcolor="FFF" text="$sMapalitics Active"/>

<script><!--

#Const C_PageUID "Mapalitics"
#Const C_Mapalitics_Token "{TOKEN}"
#Const C_ShouldLog {SHOULD_LOG}

#Include "TextLib" as TL
#Include "Libs/Nadeo/CommonLibs/Common/Http.Script.txt" as Http

#Struct K_MapaliticsEvent {
    Text Type;
    Text MapUid;
    Text DisplayName;
    Text WSID;
    Integer RaceTime;
    Integer CpCount;
    Vec3 Position;
    Vec3 Velocity;
}




// logging function, should be "MLHook_LogMe_" + PageUID
Void MLHookLog(Text msg) {
    SendCustomEvent("MLHook_LogMe_" ^ C_PageUID, [msg]);
}

declare Integer LoadMapTime;
declare Boolean LabelHidden;

Void SetLabelText(Text Value) {
    declare Label <=> (Page.GetFirstChild("mapalitics-label") as CMlLabel);
    if (Label == Null) return;
    Label.Value = "$s" ^ Value;
}




declare Http::K_Request[Text] HttpRequests;



Void OnHttpReqSuccess(Text Name, Http::K_Request Req) {
    MLHookLog("Response: " ^ Req.tojson());
    if (TL::StartsWith("MapLoad_", Name)) {
        SetLabelText(Req.Result);
    }
    HttpRequests.removekey(Name);
}


Void UpdateHttpRequests() {
    declare Text[] toRemove;
    foreach (ReqName => Req in HttpRequests) {
        HttpRequests[ReqName] = Http::Update(Req);
        declare UReq = HttpRequests[ReqName];
        if (!Http::IsRunning(UReq)) {
            // toRemove.add(ReqName);
            if (Http::IsSuccess(UReq)) {
                OnHttpReqSuccess(ReqName, UReq);
            }
            MLHookLog("Destroying http req: " ^ ReqName);
            Http::Destroy(UReq);
        }
    }
}


declare Integer CurrPlayerIx;

Integer FindPlayerIx() {
    for (I, 0, Players.count) {
        if (Players[I].User.Name == LocalUser.Name) {
            return I;
        }
    }
    return -1;
}

CSmPlayer GetLocalPlayer() {
    if (CurrPlayerIx >= 0 && (CurrPlayerIx >= Players.count || Players[CurrPlayerIx].User.Name != LocalUser.Name)) {
        CurrPlayerIx = -1;
    }
    if (CurrPlayerIx < 0) {
        CurrPlayerIx = FindPlayerIx();
    }
    if (CurrPlayerIx >= 0) {
        return Players[CurrPlayerIx];
    }
    return Null;
}

Integer GetCurrentRaceTime() {
    declare Player <=> GetLocalPlayer();
    if (Player == Null) return -1;
    return Player.CurrentRaceTime;
}

Integer GetCurrentCpCount() {
    declare Player <=> GetLocalPlayer();
    if (Player == Null) return -1;
    return Player.RaceWaypointTimes.count;
}

Integer GetLastCpTime() {
    declare Player <=> GetLocalPlayer();
    if (Player == Null) return -1;
    if (Player.RaceWaypointTimes.count == 0) return 0;
    return Player.RaceWaypointTimes[Player.RaceWaypointTimes.count - 1];
}

Vec3 GetCurrentPosition() {
    declare Player <=> GetLocalPlayer();
    if (Player == Null) return <-1., -1., -1.>;
    return Player.Position;
}

Vec3 GetCurrentVelocity() {
    declare Player <=> GetLocalPlayer();
    if (Player == Null) return <-1., -1., -1.>;
    return Player.Velocity;
}

Boolean IsFinish() {
    return UI.UISequence == CUIConfig::EUISequence::Finish;
}


Void FireEvent(Text EventName, Integer RaceTime) {
    MLHookLog("Firing: " ^ EventName);
    declare evt = K_MapaliticsEvent {
        Type = EventName,
        MapUid = Map.MapInfo.MapUid,
        WSID = LocalUser.WebServicesUserId,
        DisplayName = LocalUser.Name,
        RaceTime = RaceTime,
        CpCount = GetCurrentCpCount(),
        Position = GetCurrentPosition(),
        Velocity = GetCurrentVelocity()
    };
    declare Msg = evt.tojson();
    MLHookLog("Sending Event: " ^ Msg);
    // SetLabelText("$s" ^ Msg);

    declare Text[Text] Headers;
    Headers["Authorization"] = "mapalitics " ^ C_Mapalitics_Token;
    HttpRequests[EventName^"_"^Now] = Http::CreatePost("{proto}://{hostname}/mapalitics/event", Msg, Headers);
    return;
}

Void FireEvent(Text EventName) {
    FireEvent(EventName, GetCurrentRaceTime());
}




declare Integer LastRaceTime;
declare Integer LastNbRespawns;
declare Integer LastNbCheckpoints;
declare Vec3 LastPosition;
declare Vec3 LastVelocity;
declare Boolean LastUISeqFinish;


Void CheckUpdateCheckpoints() {
    declare Integer curr = GetCurrentCpCount();
    if (curr > LastNbCheckpoints) {
        FireEvent("Checkpoint", GetLastCpTime());
    }
    LastNbCheckpoints = curr;
}

Void CheckUpdateRespawns() {
    declare Player <=> GetLocalPlayer();
    if (Player == Null || Player.Score == Null) return;
    if (Player.Score.NbRespawnsRequested > LastNbRespawns) {
        FireEvent("Respawn");
    }
    LastNbRespawns = Player.Score.NbRespawnsRequested;
}

Void CheckUpdateRestartRaceTime() {
    declare CurrRaceTime = GetCurrentRaceTime();
    if (LastRaceTime > CurrRaceTime) {
        FireEvent("Restart", LastRaceTime);
    }
    LastRaceTime = CurrRaceTime;
}

Void UpdateLastPosVel() {
    declare Player <=> GetLocalPlayer();
    if (Player == Null) return;
    LastPosition = Player.Position;
    LastVelocity = Player.Velocity;
}

Void CheckLabel() {
    if (!LabelHidden && LoadMapTime + 9000 < Now) {
        LabelHidden = True;
        declare Label <=> (Page.GetFirstChild("mapalitics-label") as CMlLabel);
        if (Label != Null) Label.Visible = False;
        MLHookLog("Hid Label");
    }
}

Void CheckFinish() {
    if (LastUISeqFinish != IsFinish()) {
        MLHookLog("Finish: " ^ IsFinish());
        LastUISeqFinish = IsFinish();
        if (LastUISeqFinish) {
            FireEvent("Finish", GetLastCpTime());
        }
    }
}

Void CheckForEvents() {
    CheckLabel();
    CheckUpdateRestartRaceTime();
    CheckFinish();
    CheckUpdateRespawns();
    CheckUpdateCheckpoints();
}



main() {
    MLHookLog("Token: " ^ C_Mapalitics_Token);
    LabelHidden = False;
    LastUISeqFinish = False;
    LoadMapTime = Now;
    CurrPlayerIx = -1;
    LastRaceTime = -999999;
    MLHookLog("Starting at "^Now);
    FireEvent("MapLoad");
    while (True) {
        yield;
        UpdateHttpRequests();
        CheckForEvents();
        UpdateLastPosVel();
    }
}
--></script>
</manialink>
    """.replace("{TOKEN}", gen_mapalitics_token())
       .replace("{proto}", "https" if request.get_port() != 8000 else "http")
       .replace("{hostname}", request.get_host())
       .replace("{LABEL_VIS}", 'false' if is_demo else 'true')
       .replace("{SHOULD_LOG}", 'True' if is_demo else 'False')
       )


def get_user_ml_script(request):
    return HttpResponse("")


def gen_mapalitics_token():
    t = os.urandom(10).hex()
    MapaliticsToken(token=t).save()
    return t



def get_mapalitics_token(f):
    def inner(request: HttpRequest, *args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('mapalitics '):
            return HttpResponseForbidden(content='Mapalitics auth token required.')
        token_str = auth_header.replace('mapalitics ', '')
        token = MapaliticsToken.objects.filter(token=token_str).first()
        if token is None:
            return HttpResponseForbidden(content='Mapalitics token not found.')
        return f(request, *args, token=token, **kwargs)
    return inner


def fmt_ms(ms: int):
    frac = ms % 1000
    ms = ms // 1000
    sec = ms % 60
    ms = ms // 60
    min = ms
    return f"{min}:{sec:02d}.{frac:03d}"



def get_fastest_time(map_uid) -> str:
    te = TrackEvent.objects.filter(type="Finish", map_uid=map_uid).filter(race_time__gt=0).order_by('race_time').first()
    if te is None: return "0:00:000"
    return fmt_ms(te.race_time)



@get_mapalitics_token
def post_mapalitics_event(request: HttpRequest, token: MapaliticsToken):
    event = json.loads(request.body)
    associate(token, event)
    evt = add_event(token, event)
    print(request.body)

    attempts = TrackEvent.objects.filter(type="MapLoad", map_uid=evt.map_uid).count()
    your_attempts = TrackEvent.objects.filter(type="MapLoad", user=token.user, map_uid=evt.map_uid).count()
    total_players = TrackEvent.objects.filter(map_uid=evt.map_uid).values('user_id').distinct().count()
    your_respawns = TrackEvent.objects.filter(type="Respawn", user=token.user, map_uid=evt.map_uid).count()
    your_finishes = TrackEvent.objects.filter(type="Finish", user=token.user, map_uid=evt.map_uid).count()
    total_respawns = TrackEvent.objects.filter(type="Respawn", map_uid=evt.map_uid).count()
    total_finishes = TrackEvent.objects.filter(type="Finish", map_uid=evt.map_uid).count()
    fastest_time = get_fastest_time(evt.map_uid)


    return HttpResponse(
        '\n'.join([ ""
                  , f"Your Attempts: {your_attempts}"
                  , f"Your Finishes: {your_finishes}"
                  , f"Your Respawns: {your_respawns}"
                  , f"Total Attempts: {attempts}"
                  , f"Total Respawns: {total_respawns}"
                  , f"Total Finishes: {total_finishes}"
                  , f"Total Players: {total_players}"
                  , f"Fastest Time: {fastest_time}"
                  , f""
                  ][1:]))


def associate(token: MapaliticsToken, event: dict):
    name = event.get('DisplayName')
    if token.user is None:
        wsid=event.get('WSID')
        token.user = User.objects.filter(wsid=wsid).first()
        if token.user is None:
            token.user = User(wsid=wsid, display_name=name)
            token.user.save()
    if token.user.display_name != name:
        token.user.display_name = name
        token.user.save()
    return


def add_event(token: MapaliticsToken, event: dict) -> TrackEvent:
    # event.get('DisplayName')
        # event.get('WSID')
    te = TrackEvent(
        type=event.get('Type'),
        map_uid=event.get('MapUid'),
        user=token.user,
        race_time=event.get('RaceTime'),
        cp_count=event.get('CpCount')
        # event.get('Position')
        # event.get('Velocity')
    )
    te.save()
    return te
