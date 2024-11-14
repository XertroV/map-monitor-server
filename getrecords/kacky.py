import asyncio
import json
import logging
import sys
import time
from bs4 import BeautifulSoup, Tag
import bs4

from getrecords.http import get_session
from getrecords.models import CachedValue
from getrecords.view_logic import KR5_MAPS_CV_NAME, KR5_RESULTS_CV_NAME, is_close_to_cotd



async def check_kacky_results_loop():
    sleep_len = 310
    while True:
        start = time.time()
        if await is_close_to_cotd(60):
            logging.info(f"update_kacky_reloaded_5 sleeping as we are close to COTD")
            await asyncio.sleep(60)
            continue
        try:
            await update_kacky_reloaded_5()
        except Exception as e:
            logging.error(f"Exception update_kacky_reloaded_5: {e}")
        sleep_for = sleep_len - (time.time() - start)
        logging.info(f"update_kacky_reloaded_5 took {time.time() - start} s, sleeping for {sleep_for} s")
        await asyncio.sleep(sleep_for)


async def update_kacky_reloaded_5():
    await update_kr5_results()
    maps = await update_kr5_maps()
    # todo: loop through maps to get full LB so we can give ranking data


async def update_kr5_results():
    html_doc = await get_kr5_html()
    soup = BeautifulSoup(html_doc, 'html.parser')
    rows = soup.find_all('tr')
    results_doc = []
    for (i, row) in enumerate(rows):
        # if i > 100: break
        cells = row.find_all('td')
        if len(cells) < 3:
            raise Exception(f"unexpected row with less than 3 cells: {row}")
            continue
        rank = int(cells[0].text)
        nickname = cells[1].text.replace('\xa0', ' ')
        name_formatted = bs4_to_openplanet(cells[1])
        finishes = int(cells[2].text)
        avgs = float(cells[3].text)
        avgs_finished = float(cells[4].text)

        results_doc.append([rank, nickname, name_formatted, finishes, avgs, avgs_finished])

        # print(f"{rank} {nickname} ({name_formatted}) {finishes} {avgs} {avgs_finished}")
    await save_kr5_results(results_doc)
    return results_doc


async def save_kr5_results(results: list[list[str | int | float]]):
    logging.info(f"Saving KR5 results ({len(results)} results)")
    cv = await CachedValue.objects.filter(name=KR5_RESULTS_CV_NAME).afirst()
    if cv is None:
        cv = CachedValue(name=KR5_RESULTS_CV_NAME, value="")
    cv.value = json.dumps(dict(results=results, ts=time.time(), min_refresh_period=310))
    await cv.asave()
    logging.info(f"Cached kr5 results; len={len(cv.value)} B / {len(results)} elements")


async def update_kr5_maps():
    html_doc = await get_kr5_maps_html()
    soup = BeautifulSoup(html_doc, 'html.parser')
    rows = soup.find_all('tr')
    maps_doc = []
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 6:
            raise Exception(f"unexpected row with less than 6 cells: {row}")
            continue
        map_name = cells[0].text.replace('\xa0', ' ')
        map_uid = cells[0].find_next('a')['href'].split('uid=')[-1]
        map_name_formatted = bs4_to_openplanet(cells[0])
        author_name = cells[1].text.replace('\xa0', ' ')
        author_name_formatted = bs4_to_openplanet(cells[1])
        record_time = cells[2].text.replace('\xa0', ' ')
        record_holder = cells[3].text.replace('\xa0', ' ')
        record_holder_formatted = bs4_to_openplanet(cells[3])
        finishes = int(cells[4].text)
        karma = float(cells[5].text)
        maps_doc.append([map_name, map_name_formatted, map_uid, author_name, author_name_formatted, record_time, record_holder, record_holder_formatted, finishes, karma])
    await save_kr5_maps(maps_doc)
    return maps_doc


async def save_kr5_maps(maps_doc: list[list[str | int | float]]):
    logging.info(f"Saving KR5 maps ({len(maps_doc)} maps)")
    cv = await CachedValue.objects.filter(name=KR5_MAPS_CV_NAME).afirst()
    if cv is None:
        cv = CachedValue(name=KR5_MAPS_CV_NAME, value="")
    cv.value = json.dumps(dict(maps=maps_doc, ts=time.time(), min_refresh_period=310))
    await cv.asave()
    logging.info(f"Cached kr5 maps; len={len(cv.value)} B / {len(maps_doc)} elements")



def bs4_to_openplanet(cell: Tag) -> str:
    link: Tag = cell.find('a')
    if link is None:
        # raise Exception(f"unexpected cell without link: {cell}")
        return cell.text.replace('\xa0', ' ')
    op_fmt = ""
    if link.children is None:
        raise Exception(f"unexpected link without children: {link}")
        return cell.text.replace('\xa0', ' ')
    for span in link.children:
        if isinstance(span, Tag):
            if span.name == 'span':
                op_fmt += styled_span_to_op_text(span)
            else:
                raise Exception(f"unexpected tag in link: {span}")
        elif isinstance(span, bs4.element.NavigableString):
            op_fmt += span
        else:
            raise Exception(f"unexpected non-tag in link: {type(span)} {span}")
    return op_fmt.replace('\xa0', ' ')


def styled_span_to_op_text(span: Tag) -> str:
    if span.has_attr('style'):
        style = span['style']
        color = get_style_prop(style, 'color', '#ffffff')
        font_style = get_style_prop(style, 'font-style', '')
        font_weight = get_style_prop(style, 'font-weight', '')
        check_for_unrecognized_style_props(style)
        fmt_tags = fmt_color(color) + fmt_font_style(font_style) + fmt_font_weight(font_weight)
        return f"$<{fmt_tags}{span.text}$>"
    else:
        return span.text


def fmt_color(color: str) -> str:
    if color[0] != '#':
        raise Exception(f"unexpected color format: {color}")
    return f"${color[1]}{color[3]}{color[5]}"

def fmt_font_style(font_style: str) -> str:
    if font_style == 'italic':
        return "$i"
    return ""

def fmt_font_weight(font_weight: str) -> str:
    if font_weight == 'bold':
        return "$o"
    return ""

def get_style_prop(style: str, prop: str, default: str) -> str:
    if prop in style:
        return style.split(f"{prop}:")[1].split(';')[0]
    return default


# ignore letter-spacing, font-size

def check_for_unrecognized_style_props(style: str):
    props = []
    for pair in style.split(';'):
        if pair:
            props.append(pair.split(':')[0])
    for prop in props:
        if prop not in ['color', 'font-style', 'font-weight', 'letter-spacing', 'font-size']:
            raise Exception(f"unrecognized style prop: {prop}")

async def get_kr5_html():
    return TEST_HTML
    async with get_session() as session:
        try:
            async with session.get(f"https://kackyreloaded.com/event/editions/ranking.php?edition=5&raw=1") as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    raise Exception(f"Could not get KR5 ranking data: {resp.status} code.")
        except asyncio.TimeoutError as e:
            raise Exception(f"KR5 timeout for getting ranking data")


async def get_kr5_maps_html():
    return TEST_MAPS_HTML
    async with get_session() as session:
        try:
            async with session.get(f"https://kackyreloaded.com/event/editions/records.php?edition=5&raw=1") as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    raise Exception(f"Could not get KR5 maps data: {resp.status} code.")
        except asyncio.TimeoutError as e:
            raise Exception(f"KR5 timeout for getting maps data")


async def get_kr5_map_lb_html(map_uid: str):
    async with get_session() as session:
        try:
            async with session.get(f"https://kackyreloaded.com/event/editions/maps.php?uid={map_uid}&raw=1") as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    raise Exception(f"Could not get KR5 map LB data: {resp.status} code.")
        except asyncio.TimeoutError as e:
            raise Exception(f"KR5 timeout for getting map LB data")


TEST_MAPS_HTML = """
<body>
    <nav class="navbar box-shadow navbar-expand-md navbar-dark bg-ka">
        <div class="container">
            <div class="mx-auto order-0">
                <a class="navbar-brand" href="/">
                    <img src="/images/logo.png" height="10" alt="">
                </a>
                <button class="navbar-toggler" type="button" data-toggle="collapse" data-target=".dual-collapse2">
                    <span class="navbar-toggler-icon"></span>
                </button>
            </div>
            <div class="navbar-collapse collapse w-100 order-1 order-md-0 dual-collapse2">
                <ul class="navbar-nav mr-auto">
                    <li class="nav-item">
                            <a class="nav-link" href="/event/editions/ranking.php?edition=1"><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>1</span></a>
                            </li><li class="nav-item">
                            <a class="nav-link" href="/event/editions/ranking.php?edition=2"><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>2</span></a>
                            </li><li class="nav-item">
                            <a class="nav-link" href="/event/editions/ranking.php?edition=3"><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>3</span></a>
                            </li><li class="nav-item">
                            <a class="nav-link" href="/event/editions/ranking.php?edition=4"><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>4</span></a>
                            </li><li class="nav-item">
                            <a class="nav-link" href="/event/editions/ranking.php?edition=5"><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>5</span></a>
                            </li>                </ul>
            </div>

            <div class="navbar-collapse collapse w-100 order-3 dual-collapse2">
                <ul class="navbar-nav ml-auto">
					<a href="/event/editions/ranking.php?edition=0"><button
                            class="btn btn-kacky navbar-btn shadow-none box-shadow">All Editions</button></a>
					<a href="https://kacky.gg/" target="_blank"><button
                            class="btn btn-kacky navbar-btn shadow-none box-shadow">Event Page</button></a>
					<!--
					<a href="/event/leaderboard/"><button
                            class="btn btn-kacky navbar-btn shadow-none box-shadow">Leaderboard</button></a>
					-->
                    <a href="https://kacky.gg/discord" target="_blank"><img src="/images/discord.png" style="width:42px;height:42px;position:absolute;right:10px"></img></a>
					<a href="/hunting/"><button
                            class="btn btn-event-global navbar-btn shadow-none box-shadow" style="position:absolute;left:10px">Show Hunting</button></a>
                </ul>
            </div>
        </div>
    </nav>

	<div class="container">
	  <ul class="nav justify-content-center mt-2">
				<li class="nav-item">
		  <a class="nav-link" href="ranking.php?edition=5">Ranking</a>
		</li>
		<li class="nav-item">
		  <a class="nav-link active" href="records.php?edition=5">Maps</a>
		</li>
		<li class="nav-item">
		  <a class="nav-link" href="topsums.php?edition=5">TopSums</a>
		</li>
			  </ul>
	</div>
<tr><td><a class="hover-preview" data-uid="12tr_2vNsjH1_F_xJQIkS_YB2hc" href=./maps.php?uid=12tr_2vNsjH1_F_xJQIkS_YB2hc><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#301</span></a></td><td><a href=players.php?pid=98&edition=5><span style='color:#000000;'>&nbsp;/\dralonter</span></td><td>00:19.589</td><td><a href=players.php?pid=14&edition=5>lego&nbsp;piece&nbsp;53119</td><td>5</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="PuXqWJsIaUy8Q9NqgW3S0y2wdCk" href=./maps.php?uid=PuXqWJsIaUy8Q9NqgW3S0y2wdCk><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#302</span></a></td><td><a href=players.php?pid=165&edition=5><span style='color:#006600;'>P</span><span style='color:#558800;'>i</span><span style='color:#aabb00;'>z</span><span style='color:#ffdd00;'>z</span><span style='color:#ffdd00;'>l</span><span style='color:#aabb00;'>e</span><span style='color:#558800;'>K</span><span style='color:#006600;'>R</span></td><td>00:31.534</td><td><a href=players.php?pid=165&edition=5><span style='color:#006600;'>P</span><span style='color:#558800;'>i</span><span style='color:#aabb00;'>z</span><span style='color:#ffdd00;'>z</span><span style='color:#ffdd00;'>l</span><span style='color:#aabb00;'>e</span><span style='color:#558800;'>K</span><span style='color:#006600;'>R</span></td><td>151</td><td>72.73</td></tr><tr><td><a class="hover-preview" data-uid="HQvTNZXfNtvwsoIeB5j1z22zrw9" href=./maps.php?uid=HQvTNZXfNtvwsoIeB5j1z22zrw9><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#303</span></a></td><td>cs0nIjoVSkSMZfQsyEoxmQ</td><td>00:14.219</td><td><a href=players.php?pid=63077&edition=5>DugonGOD</td><td>348</td><td>50.82</td></tr><tr><td><a class="hover-preview" data-uid="19RecLHn16GT1kJqxqEshAeUfL2" href=./maps.php?uid=19RecLHn16GT1kJqxqEshAeUfL2><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#304</span></a></td><td><a href=players.php?pid=3150&edition=5>Brau<span style='color:#ff9900;'>sen</span></td><td>00:15.920</td><td><a href=players.php?pid=42991&edition=5>jxsh&nbsp;:smirkcat:</td><td>149</td><td>57.14</td></tr><tr><td><a class="hover-preview" data-uid="KlmBFvfj8WDy6qRDwGqSK7oYSmm" href=./maps.php?uid=KlmBFvfj8WDy6qRDwGqSK7oYSmm><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#305</span></a></td><td>-xQR3A6CSUmv8sFQaThLpw</td><td>00:00.000</td><td><a href=players.php?pid=&edition=5></td><td>0</td><td>0.00</td></tr><tr><td><a class="hover-preview" data-uid="2bWMcurJTDauiYQI2P2CD4ovov0" href=./maps.php?uid=2bWMcurJTDauiYQI2P2CD4ovov0><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#306</span></a></td><td><a href=players.php?pid=38&edition=5><span style='color:#ffffff;'>b</span><span style='color:#ccffee;'>o</span><span style='color:#99ffcc;'>o</span><span style='color:#66ffbb;'>s</span><span style='color:#33ff99;'>ti</span></td><td>00:51.794</td><td><a href=players.php?pid=62786&edition=5><span style='color:#000000;'>monka&nbsp;</span><span style='color:#ffffff;'>|&nbsp;</span><span style='color:#000000;'>Ď</span><span style='color:#440000;'>&Oslash;</span><span style='color:#880000;'>Ř</span><span style='color:#cc0000;'>Ά</span></td><td>88</td><td>88.00</td></tr><tr><td><a class="hover-preview" data-uid="A5BleYtqlkhSMYzReL2VLd92xX7" href=./maps.php?uid=A5BleYtqlkhSMYzReL2VLd92xX7><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#307</span></a></td><td><a href=players.php?pid=35808&edition=5>STRID:e:R</td><td>00:32.767</td><td><a href=players.php?pid=35808&edition=5>STRID:e:R</td><td>203</td><td>70.67</td></tr><tr><td><a class="hover-preview" data-uid="klTmpsTlfui1JigEnnoKs1untbe" href=./maps.php?uid=klTmpsTlfui1JigEnnoKs1untbe><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#308</span></a></td><td><a href=players.php?pid=6437&edition=5>viiru&nbsp;<span style='color:#ffcc22;'>:</span><span style='color:#ff9933;'>s</span><span style='color:#ee6633;'>m</span><span style='color:#ee6633;'>i</span><span style='color:#ee5533;'>r</span><span style='color:#ee3333;'>k</span><span style='color:#cc1177;'>c</span><span style='color:#992277;'>a</span><span style='color:#662266;'>t</span><span style='color:#333366;'>:</span></td><td>00:52.030</td><td><a href=players.php?pid=842&edition=5>SmithyTM</td><td>49</td><td>69.23</td></tr><tr><td><a class="hover-preview" data-uid="OLCQ7CdIvYDp3gK_VwcB8gwh365" href=./maps.php?uid=OLCQ7CdIvYDp3gK_VwcB8gwh365><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#309</span></a></td><td><a href=players.php?pid=246&edition=5>helvtm</td><td>00:18.070</td><td><a href=players.php?pid=8768&edition=5><span style='color:#55ff99;font-style:italic;'>J</span><span style='color:#55ff66;font-style:italic;'>e</span><span style='color:#55ff33;font-style:italic;'>t</span><span style='color:#55ff11;font-style:italic;'>.</span></td><td>23</td><td>94.12</td></tr><tr><td><a class="hover-preview" data-uid="XHN5POP6zKUEd3U_q4EZuWClRj2" href=./maps.php?uid=XHN5POP6zKUEd3U_q4EZuWClRj2><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#310</span></a></td><td><a href=players.php?pid=50445&edition=5><span style='color:#aa0000;'>&nbsp;</span><span style='color:#aa0000;letter-spacing: -0.1em;font-size:smaller'>ॢ</span><span style='color:#007766;'>St</span><span style='color:#008877;'>rat</span><span style='color:#009988;'>os</span><span style='color:#ddaa00;'>Da</span><span style='font-weight:bold;'>&nbsp;ア~ア</span></td><td>00:18.228</td><td><a href=players.php?pid=12874&edition=5><span style='color:#ff9900;'>Omega</span><span style='color:#ffffff;'>status</span></td><td>12</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="BTYDJkbp2KhfpEkGBinMELvP_Rc" href=./maps.php?uid=BTYDJkbp2KhfpEkGBinMELvP_Rc><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#311</span></a></td><td>FBLKCf8-QIGKDxP5qjAFJg</td><td>00:14.333</td><td><a href=players.php?pid=8809&edition=5><span style='color:#11dd55;'>gloя</span><span style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>dazzzyy</span></td><td>150</td><td>95.00</td></tr><tr><td><a class="hover-preview" data-uid="hvaz9GnNfH6rIpLwIEI8Gq6ZGO3" href=./maps.php?uid=hvaz9GnNfH6rIpLwIEI8Gq6ZGO3><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#312</span></a></td><td><a href=players.php?pid=55440&edition=5><span style='color:#5588ff;'>O</span><span style='color:#6688ff;'>n</span><span style='color:#8888ff;'>t</span><span style='color:#9988ff;'>r</span><span style='color:#9988ff;'>i</span><span style='color:#aa88ff;'>c</span><span style='color:#cc88ff;'>u</span><span style='color:#dd88ff;'>s</span></td><td>00:32.488</td><td><a href=players.php?pid=67319&edition=5><span style='color:#333399;'>s</span><span style='color:#3333aa;'>i</span><span style='color:#3333bb;'>g</span><span style='color:#3333dd;'>n</span><span style='color:#3333ee;'>a</span><span style='color:#3333ff;'>l</span></td><td>9</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="HgUGlMPYm6T_DUW3qTVt_Yimv36" href=./maps.php?uid=HgUGlMPYm6T_DUW3qTVt_Yimv36><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#313</span></a></td><td><a href=players.php?pid=29843&edition=5><span style='color:#0000ff;'>Norsu</span><span style='color:#ff00ff;'>TM</span></td><td>00:14.919</td><td><a href=players.php?pid=21841&edition=5>Ilnapi</td><td>135</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="nUus4R6rLuAd5QhZ4DYqdorLBXf" href=./maps.php?uid=nUus4R6rLuAd5QhZ4DYqdorLBXf><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#314</span></a></td><td>UJftYwRaQpKSI9_XQK-Whw</td><td>00:27.751</td><td><a href=players.php?pid=6420&edition=5><span style='color:#ff6600;font-weight:bold;'>f6_t</span></td><td>93</td><td>20.00</td></tr><tr><td><a class="hover-preview" data-uid="HsJJNXILs66uYAte1ZRxl2apsHg" href=./maps.php?uid=HsJJNXILs66uYAte1ZRxl2apsHg><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#315</span></a></td><td><a href=players.php?pid=12154&edition=5><span style='color:#ff0000;'>L</span><span style='color:#ee0000;'>a</span><span style='color:#dd0000;'>r</span><span style='color:#cc0000;'>s</span><span style='color:#ffeeee;'>tm</span></td><td>00:24.211</td><td><a href=players.php?pid=12154&edition=5><span style='color:#ff0000;'>L</span><span style='color:#ee0000;'>a</span><span style='color:#dd0000;'>r</span><span style='color:#cc0000;'>s</span><span style='color:#ffeeee;'>tm</span></td><td>15</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="_VdVUG6tID3yVHAEMchcsug8aHb" href=./maps.php?uid=_VdVUG6tID3yVHAEMchcsug8aHb><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#316</span></a></td><td><a href=players.php?pid=29159&edition=5><span style='color:#0077aa;'>Brau</span><span style='color:#ffffff;'>sen</span></td><td>00:16.015</td><td><a href=players.php?pid=8232&edition=5><span style='color:#ffffff;'>twig&nbsp;</span><span style='color:#ffffff;'>&laquo;&nbsp;</span><span style='color:#778899;'>т&sup3;</span></td><td>29</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="Dnf92vv66AbOjsf9Ldj7uu4MV0g" href=./maps.php?uid=Dnf92vv66AbOjsf9Ldj7uu4MV0g><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#317</span></a></td><td><a href=players.php?pid=24747&edition=5><span style='color:#ff9900;'>save&nbsp;</span><span style='color:#ffffff;'>me</span></td><td>00:20.906</td><td><a href=players.php?pid=23855&edition=5>PuWWa</td><td>11</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="0sgNgQ6JCGRGHXbpwO3lt9Fo2Gm" href=./maps.php?uid=0sgNgQ6JCGRGHXbpwO3lt9Fo2Gm><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#318</span></a></td><td><a href=players.php?pid=67295&edition=5>feklfek_</td><td>00:10.842</td><td><a href=players.php?pid=33369&edition=5><span style='color:#33aa55;'>mik</span><span style='color:#ffffff;'>mos.</span></td><td>11</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="39TuW3ZIwy9tVFOPHjZqhXSPQe7" href=./maps.php?uid=39TuW3ZIwy9tVFOPHjZqhXSPQe7><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#319</span></a></td><td><a href=players.php?pid=50445&edition=5><span style='color:#aa0000;'>&nbsp;</span><span style='color:#aa0000;letter-spacing: -0.1em;font-size:smaller'>ॢ</span><span style='color:#007766;'>St</span><span style='color:#008877;'>rat</span><span style='color:#009988;'>os</span><span style='color:#ddaa00;'>Da</span><span style='font-weight:bold;'>&nbsp;ア~ア</span></td><td>00:17.014</td><td><a href=players.php?pid=18&edition=5><span style='color:#ffffff;'>&nbsp;menfou&nbsp;|&nbsp;</span><span style='color:#66ccff;font-style:italic;font-weight:bold;'>skandear</span></td><td>24</td><td>66.67</td></tr><tr><td><a class="hover-preview" data-uid="iBk7GiEbafW_oBOh5gasGID1pze" href=./maps.php?uid=iBk7GiEbafW_oBOh5gasGID1pze><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#320</span></a></td><td><a href=players.php?pid=14&edition=5>lego&nbsp;piece&nbsp;53119</td><td>00:13.368</td><td><a href=players.php?pid=23074&edition=5><span style='color:#000000;'>monka&nbsp;</span><span style='color:#ffffff;'>|&nbsp;Sileenzz</span></td><td>13</td><td>66.67</td></tr><tr><td><a class="hover-preview" data-uid="d1j4tXPLKZLif854NsStMrf4KPi" href=./maps.php?uid=d1j4tXPLKZLif854NsStMrf4KPi><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#321</span></a></td><td><a href=players.php?pid=6587&edition=5><span style='color:#ffcc00;'>Jane</span><span style='color:#aa8800;'>t</span><span style='color:#665511;'>J</span><span style='color:#111111;'>nt</span></td><td>00:08.675</td><td><a href=players.php?pid=26396&edition=5>Its_Cam__</td><td>206</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="QaVIsgWb57FuHepBJiiBVlZrnnd" href=./maps.php?uid=QaVIsgWb57FuHepBJiiBVlZrnnd><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#322</span></a></td><td><a href=players.php?pid=67295&edition=5>feklfek_</td><td>00:19.702</td><td><a href=players.php?pid=69277&edition=5>322&nbsp;Technology</td><td>285</td><td>81.08</td></tr><tr><td><a class="hover-preview" data-uid="bfJsvZfG6JX0fzNaClghLXIESI8" href=./maps.php?uid=bfJsvZfG6JX0fzNaClghLXIESI8><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#323</span></a></td><td><a href=players.php?pid=32355&edition=5><span style='color:#00ff99;'>s</span><span style='color:#33ffcc;'>k</span><span style='color:#00ffff;'>e</span><span style='color:#00cccc;'>e</span><span style='color:#009999;'>r</span><span style='color:#006666;'>e</span><span style='color:#003333;'>m</span><span style='color:#3399cc;'>a</span><span style='color:#3366cc;'>n</span><span style='color:#0000ff;'>123</span></td><td>00:29.045</td><td><a href=players.php?pid=6343&edition=5><span style='color:#33aa55;'>nova</span><span style='color:#ffffff;'>stxr</span></td><td>5</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="01b7U9z7FseUgDzrZz5p60Busuc" href=./maps.php?uid=01b7U9z7FseUgDzrZz5p60Busuc><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#324</span></a></td><td><a href=players.php?pid=10252&edition=5>Qiraj_TM</td><td>00:40.594</td><td><a href=players.php?pid=2897&edition=5><span style='color:#ffcc00;'>S</span><span style='color:#ffffff;'>crapie</span></td><td>13</td><td>0.00</td></tr><tr><td><a class="hover-preview" data-uid="q_b567_Gmz4lRKB3kpsc5bquiUi" href=./maps.php?uid=q_b567_Gmz4lRKB3kpsc5bquiUi><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#325</span></a></td><td><a href=players.php?pid=32238&edition=5>[2][3]&nbsp;fake&nbsp;YOUMOL</td><td>00:20.411</td><td><a href=players.php?pid=13983&edition=5>Tannuleet</td><td>228</td><td>96.92</td></tr><tr><td><a class="hover-preview" data-uid="5OsziCLDDqgSGCyMz954fatpx6k" href=./maps.php?uid=5OsziCLDDqgSGCyMz954fatpx6k><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#326</span></a></td><td><a href=players.php?pid=35808&edition=5>STRID:e:R</td><td>00:16.740</td><td><a href=players.php?pid=25139&edition=5><span style='color:#ff0000;'>Ь</span><span style='color:#ff2211;'>Ł</span><span style='color:#ff4422;'>ヨ</span><span style='color:#ff6633;'>ѷ</span></td><td>533</td><td>78.33</td></tr><tr><td><a class="hover-preview" data-uid="nQ1OXECoeR0LY6bH4JvCQ1qhH2h" href=./maps.php?uid=nQ1OXECoeR0LY6bH4JvCQ1qhH2h><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#327</span></a></td><td><a href=players.php?pid=10861&edition=5>miguel_n:owo:b</td><td>00:18.645</td><td><a href=players.php?pid=66182&edition=5>BrigitteSux</td><td>83</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="A2YixZvqYkwrngsQuGD9GZRJxDc" href=./maps.php?uid=A2YixZvqYkwrngsQuGD9GZRJxDc><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#328</span></a></td><td><a href=players.php?pid=7415&edition=5><span style='color:#6600ff;'>M</span><span style='color:#6622ff;'>a</span><span style='color:#6644ff;'>j</span><span style='color:#6666ff;'>i</span></td><td>01:00.887</td><td><a href=players.php?pid=14744&edition=5><span style='color:#999966;letter-spacing: -0.1em;font-size:smaller'>daggerrrrrrrr</span></td><td>5</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="9wsBtAEu7Al63O0H1shjUnvgGe7" href=./maps.php?uid=9wsBtAEu7Al63O0H1shjUnvgGe7><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#329</span></a></td><td><a href=players.php?pid=98&edition=5><span style='color:#000000;'>&nbsp;/\dralonter</span></td><td>00:14.054</td><td><a href=players.php?pid=1043&edition=5><span style='color:#33aa55;'>Schmo</span><span style='color:#ffffff;'>bias</span></td><td>658</td><td>74.68</td></tr><tr><td><a class="hover-preview" data-uid="mIZ6hChfaM02ZIdwtyn88ke_nz2" href=./maps.php?uid=mIZ6hChfaM02ZIdwtyn88ke_nz2><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#330</span></a></td><td>9xkJZT3XQ4ibHU_ZsgVEbw</td><td>00:14.567</td><td><a href=players.php?pid=68327&edition=5><span style='color:#336699;'>Of</span><span style='color:#ffccff;'>Machi</span><span style='color:#336699;'>nations</span></td><td>93</td><td>50.00</td></tr><tr><td><a class="hover-preview" data-uid="D1pwgMErBpjLSguU1yFdbupuHi" href=./maps.php?uid=D1pwgMErBpjLSguU1yFdbupuHi><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#331</span></a></td><td><a href=players.php?pid=54343&edition=5>TM_Bum</td><td>00:29.110</td><td><a href=players.php?pid=33721&edition=5><span style='color:#ffffff;'>Dzamal&nbsp;</span><span style='color:#22bbff;'>&laquo;&nbsp;</span><span style='color:#ffffff;'>т</span><span style='color:#22bbff;'>&sup3;</span></td><td>106</td><td>95.45</td></tr><tr><td><a class="hover-preview" data-uid="YtL9LPBRHCI0pDkxuPpvT5gRCUd" href=./maps.php?uid=YtL9LPBRHCI0pDkxuPpvT5gRCUd><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#332</span></a></td><td>uEkbm5mFSjGS_qArwiy2Ew</td><td>00:13.658</td><td><a href=players.php?pid=19455&edition=5>Ricso5</td><td>102</td><td>86.36</td></tr><tr><td><a class="hover-preview" data-uid="fmuaz3jJYGw9fkX0OgpuGskK1n6" href=./maps.php?uid=fmuaz3jJYGw9fkX0OgpuGskK1n6><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#333</span></a></td><td>4K4pyQDtSvS1YEbDssa8WA</td><td>00:23.132</td><td><a href=players.php?pid=31738&edition=5>ShadowYEET17</td><td>86</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="0McPahc9mjIkP3f0pQKuD_pwHUm" href=./maps.php?uid=0McPahc9mjIkP3f0pQKuD_pwHUm><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#334</span></a></td><td>4K4pyQDtSvS1YEbDssa8WA</td><td>00:18.098</td><td><a href=players.php?pid=31063&edition=5>Faze&nbsp;balls&nbsp;:gigachad:</td><td>67</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="kMwRM7R630fZQxFGEbCwZTsTc41" href=./maps.php?uid=kMwRM7R630fZQxFGEbCwZTsTc41><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#335</span></a></td><td><a href=players.php?pid=35808&edition=5>STRID:e:R</td><td>00:05.564</td><td><a href=players.php?pid=50759&edition=5>Meldys</td><td>668</td><td>58.54</td></tr><tr><td><a class="hover-preview" data-uid="YB_CTL2XWNT3HeUlPL7NqgsUiii" href=./maps.php?uid=YB_CTL2XWNT3HeUlPL7NqgsUiii><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#336</span></a></td><td><a href=players.php?pid=14&edition=5>lego&nbsp;piece&nbsp;53119</td><td>00:09.718</td><td><a href=players.php?pid=12412&edition=5><span style='color:#000000;'>D</span><span style='color:#dd0000;'>e</span><span style='color:#ddff00;'>r</span><span style='color:#ddffbb;'>〢</span><span style='color:#33ff33;'>Schuldenberater</span></td><td>204</td><td>66.27</td></tr><tr><td><a class="hover-preview" data-uid="5GLry6Gww0A6Sqgyu9oPGBPg1f4" href=./maps.php?uid=5GLry6Gww0A6Sqgyu9oPGBPg1f4><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#337</span></a></td><td><a href=players.php?pid=7098&edition=5><span style='color:#33aa55;font-weight:bold;'>Dud</span><span style='color:#ffffff;font-weight:bold;'>aैlu</span></td><td>00:14.461</td><td><a href=players.php?pid=7098&edition=5><span style='color:#33aa55;font-weight:bold;'>Dud</span><span style='color:#ffffff;font-weight:bold;'>aैlu</span></td><td>2</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="G_gIdvp08EeESqP0EOg1lToQL99" href=./maps.php?uid=G_gIdvp08EeESqP0EOg1lToQL99><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#338</span></a></td><td><a href=players.php?pid=22286&edition=5><span style='color:#aaffcc;'>alexboi</span></td><td>00:09.354</td><td><a href=players.php?pid=28612&edition=5><span style='color:#ff0066;'>ｱ</span><span style='color:#ee3388;'>Ę</span><span style='color:#ee66aa;'>ד</span><span style='color:#dd99bb;'>ｪ</span><span style='color:#ddccdd;'>イ</span><span style='color:#ccffff;'>Ċ</span><span style='color:#ccffff;'>a</span><span style='color:#ccffee;'>&Pi;</span><span style='color:#ccffcc;'>ｪ</span><span style='color:#ccffbb;'>Ő</span><span style='color:#ccff99;'>й</span></td><td>135</td><td>64.71</td></tr><tr><td><a class="hover-preview" data-uid="AMCCNzYMjCCym4jsmBfBiqJc7Fe" href=./maps.php?uid=AMCCNzYMjCCym4jsmBfBiqJc7Fe><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#339</span></a></td><td><a href=players.php?pid=33655&edition=5><span style='color:#ff6600;'>d</span><span style='color:#ee6633;'>e</span><span style='color:#cc5555;'>q</span><span style='color:#bb5588;'>u</span><span style='color:#9944aa;'>u</span><span style='color:#8844dd;'>b</span><span style='color:#6633ff;'>i</span></td><td>00:16.259</td><td><a href=players.php?pid=6080&edition=5>simo&nbsp;<span style='color:#ffcc22;'>:</span><span style='color:#ff9933;'>s</span><span style='color:#ee6633;'>m</span><span style='color:#ee6633;'>i</span><span style='color:#ee5533;'>r</span><span style='color:#ee3333;'>k</span><span style='color:#cc1177;'>c</span><span style='color:#992277;'>a</span><span style='color:#662266;'>t</span><span style='color:#333366;'>:</span></td><td>19</td><td>93.33</td></tr><tr><td><a class="hover-preview" data-uid="GxmNv_bCxTKtI5TZWuqf949awLm" href=./maps.php?uid=GxmNv_bCxTKtI5TZWuqf949awLm><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#340</span></a></td><td><a href=players.php?pid=41&edition=5><span style='color:#ffffff;font-style:italic;font-weight:bold;'>ฬ</span><span style='font-style:italic;'>ir</span><span style='color:#ee7700;font-style:italic;'>t</span><span style='color:#ffffff;font-style:italic;'>ual</span></td><td>00:18.434</td><td><a href=players.php?pid=41&edition=5><span style='color:#ffffff;font-style:italic;font-weight:bold;'>ฬ</span><span style='font-style:italic;'>ir</span><span style='color:#ee7700;font-style:italic;'>t</span><span style='color:#ffffff;font-style:italic;'>ual</span></td><td>3</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="yTt03qmoKmXihgf76ha1_Jf0mjd" href=./maps.php?uid=yTt03qmoKmXihgf76ha1_Jf0mjd><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#341</span></a></td><td><a href=players.php?pid=22286&edition=5><span style='color:#aaffcc;'>alexboi</span></td><td>00:11.586</td><td><a href=players.php?pid=14&edition=5>lego&nbsp;piece&nbsp;53119</td><td>25</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="Q63bpldOKS9VB4bllzNNk9O7TUc" href=./maps.php?uid=Q63bpldOKS9VB4bllzNNk9O7TUc><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#342</span></a></td><td><a href=players.php?pid=28536&edition=5><span style='color:#0000ff;font-style:italic;'>P</span><span style='color:#2222ff;font-style:italic;'>r</span>0<span style='color:#6666ff;font-style:italic;'>x</span><span style='color:#8888ff;font-style:italic;'>i</span><span style='color:#9999ff;font-style:italic;'>m</span><span style='color:#bbbbff;font-style:italic;'>ate</span></td><td>00:15.133</td><td><a href=players.php?pid=11088&edition=5><span style='color:#33aa55;letter-spacing: -0.1em;font-size:smaller'>Da</span><span style='color:#ffffff;letter-spacing: -0.1em;font-size:smaller'>Best</span></td><td>47</td><td>65.38</td></tr><tr><td><a class="hover-preview" data-uid="qDOTPl98i0dzUnz6CiT4bSiTsd6" href=./maps.php?uid=qDOTPl98i0dzUnz6CiT4bSiTsd6><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#343</span></a></td><td><a href=players.php?pid=7098&edition=5><span style='color:#33aa55;font-weight:bold;'>Dud</span><span style='color:#ffffff;font-weight:bold;'>aैlu</span></td><td>00:24.176</td><td><a href=players.php?pid=8232&edition=5><span style='color:#ffffff;'>twig&nbsp;</span><span style='color:#ffffff;'>&laquo;&nbsp;</span><span style='color:#778899;'>т&sup3;</span></td><td>60</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="MRbDA3C35AifkNnDCzPzY9Ht0Wj" href=./maps.php?uid=MRbDA3C35AifkNnDCzPzY9Ht0Wj><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#344</span></a></td><td><a href=players.php?pid=20930&edition=5><span style='font-weight:bold;'>hayes:)</span></td><td>00:16.963</td><td><a href=players.php?pid=40633&edition=5><span style='color:#aa9911;'>🏃</span><span style='color:#112299;'>P</span><span style='color:#112288;'>e</span><span style='color:#2288aa;'>&euml;</span><span style='color:#11aa33;'>w</span></td><td>99</td><td>79.31</td></tr><tr><td><a class="hover-preview" data-uid="A7fwypC0z_zLwVqr0GN3sIN8Y73" href=./maps.php?uid=A7fwypC0z_zLwVqr0GN3sIN8Y73><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#345</span></a></td><td>vmqS_xBdQFOArihA4cg_rQ</td><td>00:32.646</td><td><a href=players.php?pid=34205&edition=5><span style='color:#ff9900;'>でech</span><span style='color:#ffffff;'>.str</span><span style='color:#ff9900;'>ツ</span></td><td>40</td><td>12.50</td></tr><tr><td><a class="hover-preview" data-uid="P3bmK1SOFAzeDI2aYOZKk6Q6Rmg" href=./maps.php?uid=P3bmK1SOFAzeDI2aYOZKk6Q6Rmg><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#346</span></a></td><td><a href=players.php?pid=4&edition=5><span style='color:#00ff00;font-weight:bold;'>ins</span></td><td>00:25.319</td><td><a href=players.php?pid=52010&edition=5>Joyboy</td><td>2</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="ScMCq50UmItvolFW9RD4XRf0y_b" href=./maps.php?uid=ScMCq50UmItvolFW9RD4XRf0y_b><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#347</span></a></td><td><a href=players.php?pid=8809&edition=5><span style='color:#11dd55;'>gloя</span><span style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>dazzzyy</span></td><td>00:00.000</td><td><a href=players.php?pid=&edition=5></td><td>0</td><td>0.00</td></tr><tr><td><a class="hover-preview" data-uid="oGxHm9qVbUrbBZrcb0SSinDpspe" href=./maps.php?uid=oGxHm9qVbUrbBZrcb0SSinDpspe><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#348</span></a></td><td><a href=players.php?pid=1602&edition=5><span style='color:#339900;'>toto&nbsp;:ezy:</span></td><td>00:15.315</td><td><a href=players.php?pid=53854&edition=5><span style='color:#11dd55;'>gloя</span><span style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='color:#000000;font-style:italic;'>Yoshy</span></td><td>631</td><td>90.60</td></tr><tr><td><a class="hover-preview" data-uid="J7zb0MAmobhKUem7m53lZYoZGZa" href=./maps.php?uid=J7zb0MAmobhKUem7m53lZYoZGZa><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#349</span></a></td><td><a href=players.php?pid=42991&edition=5>jxsh&nbsp;:smirkcat:</td><td>00:15.703</td><td><a href=players.php?pid=14&edition=5>lego&nbsp;piece&nbsp;53119</td><td>108</td><td>92.86</td></tr><tr><td><a class="hover-preview" data-uid="HqhEuSgnQFyQEazNlGCarYAyA7f" href=./maps.php?uid=HqhEuSgnQFyQEazNlGCarYAyA7f><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#350</span></a></td><td><a href=players.php?pid=25461&edition=5><span style='color:#ffffdd;font-weight:bold;'>I</span><span style='color:#ffffee;font-weight:bold;'>nt</span><span style='color:#ffffff;font-weight:bold;'>ax</span></td><td>00:18.619</td><td><a href=players.php?pid=18&edition=5><span style='color:#ffffff;'>&nbsp;menfou&nbsp;|&nbsp;</span><span style='color:#66ccff;font-style:italic;font-weight:bold;'>skandear</span></td><td>21</td><td>0.00</td></tr><tr><td><a class="hover-preview" data-uid="VsQanouMMRCKTG8SrJ2JFwib84j" href=./maps.php?uid=VsQanouMMRCKTG8SrJ2JFwib84j><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#351</span></a></td><td><a href=players.php?pid=1602&edition=5><span style='color:#339900;'>toto&nbsp;:ezy:</span></td><td>00:15.384</td><td><a href=players.php?pid=33629&edition=5><span style='color:#ffffff;'>&alpha;&iota;г</span><span style='color:#777777;'>&nbsp;ı|ı&nbsp;</span><span style='color:#aadddd;'>ch</span><span style='color:#77dddd;'>ar</span><span style='color:#44dddd;'>les</span></td><td>358</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="jPEeqyzyfKbonf2pmaXWM6oXEKg" href=./maps.php?uid=jPEeqyzyfKbonf2pmaXWM6oXEKg><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#352</span></a></td><td><a href=players.php?pid=6587&edition=5><span style='color:#ffcc00;'>Jane</span><span style='color:#aa8800;'>t</span><span style='color:#665511;'>J</span><span style='color:#111111;'>nt</span></td><td>00:21.139</td><td><a href=players.php?pid=33369&edition=5><span style='color:#33aa55;'>mik</span><span style='color:#ffffff;'>mos.</span></td><td>11</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="8UW4JU7zq7xvUfJdRDKFxrx7LIh" href=./maps.php?uid=8UW4JU7zq7xvUfJdRDKFxrx7LIh><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#353</span></a></td><td><a href=players.php?pid=63656&edition=5>rogurgo</td><td>00:16.738</td><td><a href=players.php?pid=41&edition=5><span style='color:#ffffff;font-style:italic;font-weight:bold;'>ฬ</span><span style='font-style:italic;'>ir</span><span style='color:#ee7700;font-style:italic;'>t</span><span style='color:#ffffff;font-style:italic;'>ual</span></td><td>135</td><td>96.36</td></tr><tr><td><a class="hover-preview" data-uid="zKWT8qRLLXgqDL6D2F5Vx9OU_lj" href=./maps.php?uid=zKWT8qRLLXgqDL6D2F5Vx9OU_lj><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#354</span></a></td><td><a href=players.php?pid=2816&edition=5><span style='color:#11dd55;'>gloя</span><span style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>Kcedus</span></td><td>00:18.529</td><td><a href=players.php?pid=48687&edition=5><span style='color:#ff0000;'>Le</span><span style='color:#ffffff;'>m</span><span style='color:#0000ff;'>on&nbsp;</span><span style='color:#ffffff;'>:)&nbsp;</span><span style='color:#ffff00;'>ᄓ&nbsp;</span><span style='color:#ffffff;'>boosт&sup3;</span></td><td>20</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="V0VLK3maMIQYkNLPaJTOpVfFV0d" href=./maps.php?uid=V0VLK3maMIQYkNLPaJTOpVfFV0d><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#355</span></a></td><td><a href=players.php?pid=21&edition=5><span style='color:#ff00ff;font-weight:bold;'></span><span style='color:#ff3399;font-weight:bold;'>&nbsp;</span><span style='color:#ff6666;font-style:italic;font-weight:bold;'>d</span><span style='color:#ff5577;font-style:italic;font-weight:bold;'>r</span><span style='color:#ff5588;font-style:italic;font-weight:bold;'>a</span><span style='color:#ff4488;font-style:italic;font-weight:bold;'>g</span><span style='color:#ff3399;font-style:italic;font-weight:bold;'>o</span><span style='color:#ff22aa;font-style:italic;font-weight:bold;'>n</span><span style='color:#ff22bb;font-style:italic;font-weight:bold;'>p</span><span style='color:#ff11bb;font-style:italic;font-weight:bold;'>n</span><span style='color:#ff00cc;font-style:italic;font-weight:bold;'>tm&nbsp;[Cheese&nbsp;Police]</span></td><td>00:09.636</td><td><a href=players.php?pid=8772&edition=5><span style='color:#11dd55;'>gloя</span><span style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='color:#3366cc;font-style:italic;'>ɀe</span><span style='color:#3377dd;font-style:italic;'>nt</span><span style='color:#3388ee;font-style:italic;'>ri</span><span style='color:#3399ff;font-style:italic;'>an</span></td><td>141</td><td>54.76</td></tr><tr><td><a class="hover-preview" data-uid="x9nYfWYxayZpH28VkIIDxW1K3N4" href=./maps.php?uid=x9nYfWYxayZpH28VkIIDxW1K3N4><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#356</span></a></td><td><a href=players.php?pid=24955&edition=5>golden&nbsp;:smirkcat:</td><td>00:12.817</td><td><a href=players.php?pid=848&edition=5><span style='color:#cc3300;'>m</span><span style='color:#dd2244;'>a</span><span style='color:#ee1188;'>x</span><span style='color:#ff00cc;'>m</span><span style='color:#ff00cc;'>a</span><span style='color:#aa11dd;'>d</span><span style='color:#5522ee;'>4</span><span style='color:#0033ff;'>6</span></td><td>331</td><td>84.11</td></tr><tr><td><a class="hover-preview" data-uid="bxtzU5EzGXTHENOvmdhuEmmD204" href=./maps.php?uid=bxtzU5EzGXTHENOvmdhuEmmD204><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#357</span></a></td><td><a href=players.php?pid=43202&edition=5>Kekeciam</td><td>00:28.752</td><td><a href=players.php?pid=24549&edition=5><span style='color:#660000;'>M</span><span style='color:#bb0000;'>O</span><span style='color:#ff0000;'>N</span><span style='color:#ff0000;'>K</span><span style='color:#ff0066;'>A&nbsp;</span><span style='color:#ffffff;'>|&nbsp;</span><span style='color:#33aa55;font-weight:bold;'>.</span><span style='color:#ffffff;letter-spacing: -0.1em;font-size:smaller'>bobo</span></td><td>141</td><td>14.10</td></tr><tr><td><a class="hover-preview" data-uid="IHH4ALXy0CN3ZuTulJTMB7V28H6" href=./maps.php?uid=IHH4ALXy0CN3ZuTulJTMB7V28H6><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#358</span></a></td><td><a href=players.php?pid=6437&edition=5>viiru&nbsp;<span style='color:#ffcc22;'>:</span><span style='color:#ff9933;'>s</span><span style='color:#ee6633;'>m</span><span style='color:#ee6633;'>i</span><span style='color:#ee5533;'>r</span><span style='color:#ee3333;'>k</span><span style='color:#cc1177;'>c</span><span style='color:#992277;'>a</span><span style='color:#662266;'>t</span><span style='color:#333366;'>:</span></td><td>00:17.674</td><td><a href=players.php?pid=6420&edition=5><span style='color:#ff6600;font-weight:bold;'>f6_t</span></td><td>7</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="BdUNm74ofD_WObEzCvjYrVXFVg5" href=./maps.php?uid=BdUNm74ofD_WObEzCvjYrVXFVg5><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#359</span></a></td><td><a href=players.php?pid=32305&edition=5>akimaNN7</td><td>00:19.584</td><td><a href=players.php?pid=68800&edition=5><span style='color:#cc0000;'>ant1socialik0_o</span></td><td>66</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="3RHyjM8jlxp9uJuo6BmlCaoEi9h" href=./maps.php?uid=3RHyjM8jlxp9uJuo6BmlCaoEi9h><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#360</span></a></td><td><a href=players.php?pid=43329&edition=5><span style='color:#55eeff;'>|</span><span style='color:#8833ff;'>meg</span><span style='color:#55eeff;'>|</span></td><td>00:20.568</td><td><a href=players.php?pid=369&edition=5>slujshshsksuysh13</td><td>7</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="LI9z5g1xPsdcne3aY3xhC80wQzh" href=./maps.php?uid=LI9z5g1xPsdcne3aY3xhC80wQzh><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#361</span></a></td><td><a href=players.php?pid=33369&edition=5><span style='color:#33aa55;'>mik</span><span style='color:#ffffff;'>mos.</span></td><td>00:13.589</td><td><a href=players.php?pid=25139&edition=5><span style='color:#ff0000;'>Ь</span><span style='color:#ff2211;'>Ł</span><span style='color:#ff4422;'>ヨ</span><span style='color:#ff6633;'>ѷ</span></td><td>554</td><td>90.99</td></tr><tr><td><a class="hover-preview" data-uid="kQuSGu0lOxGImfufxWjLCY9TnX" href=./maps.php?uid=kQuSGu0lOxGImfufxWjLCY9TnX><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#362</span></a></td><td><a href=players.php?pid=55440&edition=5><span style='color:#5588ff;'>O</span><span style='color:#6688ff;'>n</span><span style='color:#8888ff;'>t</span><span style='color:#9988ff;'>r</span><span style='color:#9988ff;'>i</span><span style='color:#aa88ff;'>c</span><span style='color:#cc88ff;'>u</span><span style='color:#dd88ff;'>s</span></td><td>00:17.450</td><td><a href=players.php?pid=8650&edition=5>Light.TM</td><td>103</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="wtkgTLxylvVz8C6mLNlWkM_eTLd" href=./maps.php?uid=wtkgTLxylvVz8C6mLNlWkM_eTLd><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#363</span></a></td><td><a href=players.php?pid=5&edition=5><span style='color:#ffdd00;font-weight:bold;'>B</span><span style='color:#ffcc00;font-weight:bold;'>ea</span><span style='color:#ff9911;font-weight:bold;'>t</span><span style='color:#ff8822;font-weight:bold;'>r</span><span style='color:#ff7722;font-weight:bold;'>i</span><span style='color:#ff5533;font-weight:bold;'>c</span><span style='color:#ff4433;font-weight:bold;'>e</span></td><td>00:16.409</td><td><a href=players.php?pid=122&edition=5>PorkyP</td><td>32</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="KyrU0xOcKYkwySf6PSLpcRzd8Y2" href=./maps.php?uid=KyrU0xOcKYkwySf6PSLpcRzd8Y2><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#364</span></a></td><td><a href=players.php?pid=3150&edition=5>Brau<span style='color:#ff9900;'>sen</span></td><td>00:08.531</td><td><a href=players.php?pid=62289&edition=5><span style='color:#000099;'>S</span><span style='color:#1122aa;'>u</span><span style='color:#2244bb;'>p</span><span style='color:#3366cc;'>r</span><span style='color:#4488dd;'>e</span><span style='color:#55aaee;'>m</span><span style='color:#66ccff;'>e</span><span style='color:#66ccff;'>o</span><span style='color:#77ddff;'>r</span><span style='color:#77ddee;'>e</span><span style='color:#88eeee;'>o</span><span style='color:#88eedd;'>1</span><span style='color:#99ffdd;'>2</span><span style='color:#99ffcc;'>1</span></td><td>312</td><td>62.71</td></tr><tr><td><a class="hover-preview" data-uid="Ba9NaucPTEJ7wcWXhreKhuiZ675" href=./maps.php?uid=Ba9NaucPTEJ7wcWXhreKhuiZ675><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#365</span></a></td><td><a href=players.php?pid=1710&edition=5><span style='color:#ffffff;font-style:italic;'>&raquo;</span><span style='color:#99ffff;font-style:italic;'>エ</span><span style='color:#66ffff;font-style:italic;'>c</span><span style='color:#33ffff;font-style:italic;'>e</span><span style='color:#000000;font-style:italic;'>.</span></td><td>00:10.168</td><td><a href=players.php?pid=15025&edition=5>Persiano</td><td>1533</td><td>34.92</td></tr><tr><td><a class="hover-preview" data-uid="3ogT4tnpci3MXwE7pDlaerAWC8l" href=./maps.php?uid=3ogT4tnpci3MXwE7pDlaerAWC8l><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#366</span></a></td><td><a href=players.php?pid=7415&edition=5><span style='color:#6600ff;'>M</span><span style='color:#6622ff;'>a</span><span style='color:#6644ff;'>j</span><span style='color:#6666ff;'>i</span></td><td>00:33.132</td><td><a href=players.php?pid=7379&edition=5><span style='color:#ff00cc;font-weight:bold;'>H</span><span style='color:#dd11bb;font-weight:bold;'>E</span><span style='color:#bb22aa;font-weight:bold;'>G</span><span style='color:#993399;font-weight:bold;'>E</span></td><td>111</td><td>48.15</td></tr><tr><td><a class="hover-preview" data-uid="HM5BsdywqCGJNt8A9CaEYHiA64f" href=./maps.php?uid=HM5BsdywqCGJNt8A9CaEYHiA64f><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#367</span></a></td><td><a href=players.php?pid=52332&edition=5>FriendlySnowbal</td><td>00:10.005</td><td><a href=players.php?pid=68800&edition=5><span style='color:#cc0000;'>ant1socialik0_o</span></td><td>738</td><td>91.60</td></tr><tr><td><a class="hover-preview" data-uid="ccECsQFkuA54H5XV0U0yg2Gt8Cf" href=./maps.php?uid=ccECsQFkuA54H5XV0U0yg2Gt8Cf><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#368</span></a></td><td>g9u7BFooRoS37LimR6zpgg</td><td>00:21.029</td><td><a href=players.php?pid=21838&edition=5>Hysteri<span style='color:#0000ff;'>k</span><span style='color:#ffffff;'>T</span><span style='color:#ff0000;'>M</span></td><td>437</td><td>50.00</td></tr><tr><td><a class="hover-preview" data-uid="35RvvpN7oegxzCpKlCyIIWJAQeh" href=./maps.php?uid=35RvvpN7oegxzCpKlCyIIWJAQeh><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#369</span></a></td><td><a href=players.php?pid=10001&edition=5><span style='color:#33aa55;font-style:italic;'>Jac</span><span style='color:#ffffff;font-style:italic;'>kk</span></td><td>00:13.011</td><td><a href=players.php?pid=66802&edition=5><span style='color:#9900ff;'>D</span><span style='color:#bb00ff;'>o</span><span style='color:#dd00ff;'>s</span><span style='color:#dd00ff;'>l</span><span style='color:#ee00ff;'>yd</span><span style='color:#ff00ff;'>oo</span></td><td>588</td><td>60.12</td></tr><tr><td><a class="hover-preview" data-uid="K_mLJHW2rArGHis0sA1cG2kK4b4" href=./maps.php?uid=K_mLJHW2rArGHis0sA1cG2kK4b4><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#370</span></a></td><td><a href=players.php?pid=22000&edition=5>SuperrKuzco</td><td>00:05.798</td><td><a href=players.php?pid=61200&edition=5>GxRustyxG</td><td>91</td><td>56.25</td></tr><tr><td><a class="hover-preview" data-uid="cBXu6QP1TXJvRELT5Jyh1R2HPTb" href=./maps.php?uid=cBXu6QP1TXJvRELT5Jyh1R2HPTb><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#371</span></a></td><td><a href=players.php?pid=8768&edition=5><span style='color:#55ff99;font-style:italic;'>J</span><span style='color:#55ff66;font-style:italic;'>e</span><span style='color:#55ff33;font-style:italic;'>t</span><span style='color:#55ff11;font-style:italic;'>.</span></td><td>00:08.106</td><td><a href=players.php?pid=67235&edition=5><span style='color:#ee55cc;'>m</span><span style='color:#ee66cc;'>o</span><span style='color:#ee77cc;'>s</span><span style='color:#ee88cc;'>h</span><span style='color:#ee99cc;'>i</span><span style='color:#eeaacc;'>i</span><span style='color:#eebbcc;'>c</span><span style='color:#eecccc;'>s.</span><span style='color:#ccccff;'>K</span><span style='color:#ccccff;'>a</span><span style='color:#bbbbff;'>c</span><span style='color:#bb99ff;'>c</span><span style='color:#aa88ff;'>h</span><span style='color:#9966ff;'>i</span></td><td>1072</td><td>50.61</td></tr><tr><td><a class="hover-preview" data-uid="mqOdcxyK_o9KfSsq3pZsE6suvY2" href=./maps.php?uid=mqOdcxyK_o9KfSsq3pZsE6suvY2><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#372</span></a></td><td><a href=players.php?pid=31740&edition=5><span style='color:#33ff00;'>C</span><span style='color:#77ff55;'>ђ</span><span style='color:#bbffaa;'>น</span><span style='color:#ffffff;'>r</span><span style='color:#ffffff;'>г</span><span style='color:#ffffaa;'>ơ</span><span style='color:#ffff55;'>3</span><span style='color:#ffff00;'>6</span></td><td>00:17.135</td><td><a href=players.php?pid=6343&edition=5><span style='color:#33aa55;'>nova</span><span style='color:#ffffff;'>stxr</span></td><td>10</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="X53y_hiJOSlGcpkdKMlxwnQt1m7" href=./maps.php?uid=X53y_hiJOSlGcpkdKMlxwnQt1m7><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#373</span></a></td><td><a href=players.php?pid=35808&edition=5>STRID:e:R</td><td>00:23.367</td><td><a href=players.php?pid=18&edition=5><span style='color:#ffffff;'>&nbsp;menfou&nbsp;|&nbsp;</span><span style='color:#66ccff;font-style:italic;font-weight:bold;'>skandear</span></td><td>29</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="lhEMZDKNyswfxXv9AY4Ef6WvSpe" href=./maps.php?uid=lhEMZDKNyswfxXv9AY4Ef6WvSpe><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#374</span></a></td><td>Rss2yw8iTUG4MtdzAG1t5A</td><td>00:18.667</td><td><a href=players.php?pid=33721&edition=5><span style='color:#ffffff;'>Dzamal&nbsp;</span><span style='color:#22bbff;'>&laquo;&nbsp;</span><span style='color:#ffffff;'>т</span><span style='color:#22bbff;'>&sup3;</span></td><td>8</td><td>100.00</td></tr><tr><td><a class="hover-preview" data-uid="iAUPMCKI2VwDMqx0Rx9BhlewML1" href=./maps.php?uid=iAUPMCKI2VwDMqx0Rx9BhlewML1><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>Kack</span><span style='color:#0055aa;font-style:italic;font-weight:bold;'>y&nbsp;Re</span><span style='color:#0099aa;font-style:italic;font-weight:bold;'>lo</span><span style='color:#66aa00;font-style:italic;font-weight:bold;'>ad</span><span style='color:#aaaa00;font-style:italic;font-weight:bold;'>ed&nbsp;</span><span style='color:#44ff00;font-style:italic;font-weight:bold;'>#375</span></a></td><td>yU-Nf7tZRZGKPrp7pqc9FA</td><td>00:18.848</td><td><a href=players.php?pid=8013&edition=5><span style='color:#6633cc;'>:painsge:&nbsp;</span><span style='color:#ff9900;'>Skill&nbsp;</span><span style='color:#ffffff;'>Issue</span></td><td>288</td><td>63.64</td></tr>
"""


TEST_HTML = """
<body>
    <nav class="navbar box-shadow navbar-expand-md navbar-dark bg-ka">
        <div class="container">
            <div class="mx-auto order-0">
                <a class="navbar-brand" href="/">
                    <img src="/images/logo.png" height="10" alt="">
                </a>
                <button class="navbar-toggler" type="button" data-toggle="collapse" data-target=".dual-collapse2">
                    <span class="navbar-toggler-icon"></span>
                </button>
            </div>
            <div class="navbar-collapse collapse w-100 order-1 order-md-0 dual-collapse2">
                <ul class="navbar-nav mr-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="/event/editions/ranking.php?edition=1"><span
                                style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span
                                style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span
                                style='color:#66aa00;font-style:italic;font-weight:bold;'>1</span></a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/event/editions/ranking.php?edition=2"><span
                                style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span
                                style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span
                                style='color:#66aa00;font-style:italic;font-weight:bold;'>2</span></a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/event/editions/ranking.php?edition=3"><span
                                style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span
                                style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span
                                style='color:#66aa00;font-style:italic;font-weight:bold;'>3</span></a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/event/editions/ranking.php?edition=4"><span
                                style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span
                                style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span
                                style='color:#66aa00;font-style:italic;font-weight:bold;'>4</span></a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/event/editions/ranking.php?edition=5"><span
                                style='color:#aaaa00;font-style:italic;font-weight:bold;'>K</span><span
                                style='color:#0055aa;font-style:italic;font-weight:bold;'>R</span><span
                                style='color:#66aa00;font-style:italic;font-weight:bold;'>5</span></a>
                    </li>
                </ul>
            </div>

            <div class="navbar-collapse collapse w-100 order-3 dual-collapse2">
                <ul class="navbar-nav ml-auto">
                    <a href="/event/editions/ranking.php?edition=0"><button
                            class="btn btn-kacky navbar-btn shadow-none box-shadow">All Editions</button></a>
                    <a href="https://kacky.gg/" target="_blank"><button
                            class="btn btn-kacky navbar-btn shadow-none box-shadow">Event Page</button></a>
                    <!--
					<a href="/event/leaderboard/"><button
                            class="btn btn-kacky navbar-btn shadow-none box-shadow">Leaderboard</button></a>
					-->
                    <a href="https://kacky.gg/discord" target="_blank"><img src="/images/discord.png"
                            style="width:42px;height:42px;position:absolute;right:10px"></img></a>
                    <a href="/hunting/"><button class="btn btn-event-global navbar-btn shadow-none box-shadow"
                            style="position:absolute;left:10px">Show Hunting</button></a>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container">
        <ul class="nav justify-content-center mt-2">
            <li class="nav-item">
                <a class="nav-link" href="ranking.php?edition=5">Ranking</a>
            </li>
            <li class="nav-item">
                <a class="nav-link active" href="records.php?edition=5">Maps</a>
            </li>
            <li class="nav-item">
                <a class="nav-link" href="topsums.php?edition=5">TopSums</a>
            </li>
        </ul>
    </div>

    <tr>
        <td>1</td>
        <td><a href=players.php?pid=25376&edition=5><span style='color:#ffffff;'>iiHugo</span><span
                    style='color:#0099cc;'>&nbsp;&laquo;</span><span style='color:#ffffff;'>&nbsp;т</span><span
                    style='color:#0099cc;'>&sup3;</span></a></td>
        <td>74</td>
        <td>181.907</td>
        <td>49.230</td>
    </tr>
    <tr>
        <td>2</td>
        <td><a href=players.php?pid=41&edition=5><span
                    style='color:#ffffff;font-style:italic;font-weight:bold;'>ฬ</span><span
                    style='font-style:italic;'>ir</span><span style='color:#ee7700;font-style:italic;'>t</span><span
                    style='color:#ffffff;font-style:italic;'>ual</span></a></td>
        <td>73</td>
        <td>331.040</td>
        <td>66.137</td>
    </tr>
    <tr>
        <td>3</td>
        <td><a href=players.php?pid=6420&edition=5><span style='color:#ff6600;font-weight:bold;'>f6_t</span></a></td>
        <td>73</td>
        <td>331.627</td>
        <td>66.740</td>
    </tr>
    <tr>
        <td>4</td>
        <td><a href=players.php?pid=33369&edition=5><span style='color:#33aa55;'>mik</span><span
                    style='color:#ffffff;'>mos.</span></a></td>
        <td>72</td>
        <td>444.987</td>
        <td>46.861</td>
    </tr>
    <tr>
        <td>5</td>
        <td><a href=players.php?pid=23074&edition=5><span style='color:#000000;'>monka&nbsp;</span><span
                    style='color:#ffffff;'>|&nbsp;Sileenzz</span></a></td>
        <td>72</td>
        <td>475.987</td>
        <td>79.153</td>
    </tr>
    <tr>
        <td>6</td>
        <td><a href=players.php?pid=842&edition=5>SmithyTM</a></td>
        <td>71</td>
        <td>597.507</td>
        <td>67.789</td>
    </tr>
    <tr>
        <td>7</td>
        <td><a href=players.php?pid=873&edition=5>TeraTM</a></td>
        <td>71</td>
        <td>616.467</td>
        <td>87.817</td>
    </tr>
    <tr>
        <td>8</td>
        <td><a href=players.php?pid=6080&edition=5>simo&nbsp;<span style='color:#ffcc22;'>:</span><span
                    style='color:#ff9933;'>s</span><span style='color:#ee6633;'>m</span><span
                    style='color:#ee6633;'>i</span><span style='color:#ee5533;'>r</span><span
                    style='color:#ee3333;'>k</span><span style='color:#cc1177;'>c</span><span
                    style='color:#992277;'>a</span><span style='color:#662266;'>t</span><span
                    style='color:#333366;'>:</span></a></td>
        <td>70</td>
        <td>723.920</td>
        <td>61.343</td>
    </tr>
    <tr>
        <td>9</td>
        <td><a href=players.php?pid=29565&edition=5>[<span style='color:#ff0000;'>WH</span><span
                    style='color:#ffff88;'>OP</span>]SSano</a></td>
        <td>70</td>
        <td>761.653</td>
        <td>101.771</td>
    </tr>
    <tr>
        <td>10</td>
        <td><a href=players.php?pid=814&edition=5><span style='color:#0000dd;'>&raquo;ғฟ๏&laquo;&nbsp;</span><span
                    style='color:#ffffff;'>Ŀ&iota;и&kappa;.</span><span style='color:#ff0000;'>*&nbsp;</span><span
                    style='color:#bbbbbb;'>Law</span></a></td>
        <td>69</td>
        <td>856.040</td>
        <td>60.913</td>
    </tr>
    <tr>
        <td>11</td>
        <td><a href=players.php?pid=23083&edition=5><span style='color:#000000;'>monka&nbsp;</span><span
                    style='color:#ffffff;'>|&nbsp;zetos</span></a></td>
        <td>69</td>
        <td>905.187</td>
        <td>114.333</td>
    </tr>
    <tr>
        <td>12</td>
        <td><a href=players.php?pid=2897&edition=5><span style='color:#ffcc00;'>S</span><span
                    style='color:#ffffff;'>crapie</span></a></td>
        <td>69</td>
        <td>921.560</td>
        <td>132.130</td>
    </tr>
    <tr>
        <td>13</td>
        <td><a href=players.php?pid=11088&edition=5><span
                    style='color:#33aa55;letter-spacing: -0.1em;font-size:smaller'>Da</span><span
                    style='color:#ffffff;letter-spacing: -0.1em;font-size:smaller'>Best</span></a></td>
        <td>67</td>
        <td>1157.733</td>
        <td>101.940</td>
    </tr>
    <tr>
        <td>14</td>
        <td><a href=players.php?pid=14&edition=5><span style='color:#33aa55;font-style:italic;'>Yek</span><span
                    style='color:#ffffff;font-style:italic;'>ky.</span></a></td>
        <td>66</td>
        <td>1271.947</td>
        <td>81.758</td>
    </tr>
    <tr>
        <td>15</td>
        <td><a href=players.php?pid=55440&edition=5><span style='color:#5588ff;'>O</span><span
                    style='color:#6688ff;'>n</span><span style='color:#8888ff;'>t</span><span
                    style='color:#9988ff;'>r</span><span style='color:#9988ff;'>i</span><span
                    style='color:#aa88ff;'>c</span><span style='color:#cc88ff;'>u</span><span
                    style='color:#dd88ff;'>s</span></a></td>
        <td>66</td>
        <td>1289.147</td>
        <td>101.303</td>
    </tr>
    <tr>
        <td>16</td>
        <td><a href=players.php?pid=48687&edition=5><span style='color:#ff0000;'>Le</span><span
                    style='color:#ffffff;'>m</span><span style='color:#0000ff;'>on&nbsp;</span><span
                    style='color:#ffffff;'>:)&nbsp;</span><span style='color:#ffff00;'>ᄓ&nbsp;</span><span
                    style='color:#ffffff;'>boosт&sup3;</span></a></td>
        <td>66</td>
        <td>1321.067</td>
        <td>137.576</td>
    </tr>
    <tr>
        <td>17</td>
        <td><a href=players.php?pid=7339&edition=5>Bijan</a></td>
        <td>66</td>
        <td>1328.107</td>
        <td>145.576</td>
    </tr>
    <tr>
        <td>18</td>
        <td><a href=players.php?pid=19311&edition=5><span style='color:#ff9900;'>Pi</span><span
                    style='color:#ffffff;'>a:YEK:</span></a></td>
        <td>65</td>
        <td>1437.293</td>
        <td>119.954</td>
    </tr>
    <tr>
        <td>19</td>
        <td><a href=players.php?pid=18&edition=5><span style='color:#ffffff;'>&nbsp;menfou&nbsp;|&nbsp;</span><span
                    style='color:#66ccff;font-style:italic;font-weight:bold;'>skandear</span></a></td>
        <td>65</td>
        <td>1456.253</td>
        <td>141.831</td>
    </tr>
    <tr>
        <td>20</td>
        <td><a href=players.php?pid=8232&edition=5><span style='color:#ffffff;'>twig&nbsp;</span><span
                    style='color:#ffffff;'>&laquo;&nbsp;</span><span style='color:#778899;'>т&sup3;</span></a></td>
        <td>61</td>
        <td>2000.773</td>
        <td>164.885</td>
    </tr>
    <tr>
        <td>21</td>
        <td><a href=players.php?pid=38350&edition=5><span style='font-weight:bold;'>И&aelig;</span><span
                    style='color:#ee2200;font-weight:bold;'>lie</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>Ѫ</span></a></td>
        <td>59</td>
        <td>2266.133</td>
        <td>168.814</td>
    </tr>
    <tr>
        <td>22</td>
        <td><a href=players.php?pid=2463&edition=5>Yannex</a></td>
        <td>59</td>
        <td>2283.520</td>
        <td>190.915</td>
    </tr>
    <tr>
        <td>23</td>
        <td><a href=players.php?pid=7098&edition=5><span style='color:#33aa55;font-weight:bold;'>Dud</span><span
                    style='color:#ffffff;font-weight:bold;'>aैlu</span></a></td>
        <td>56</td>
        <td>2649.520</td>
        <td>155.607</td>
    </tr>
    <tr>
        <td>24</td>
        <td><a href=players.php?pid=1325&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Wingo</span></a></td>
        <td>55</td>
        <td>2761.507</td>
        <td>129.327</td>
    </tr>
    <tr>
        <td>25</td>
        <td><a href=players.php?pid=16199&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='color:#996600;font-style:italic;'>K</span><span
                    style='color:#aa6600;font-style:italic;'>a</span><span
                    style='color:#aa7700;font-style:italic;'>k</span><span
                    style='color:#bb7700;font-style:italic;'>ki</span><span
                    style='color:#bb7700;font-style:italic;'>e</span><span
                    style='color:#bb7711;font-style:italic;'>b</span><span
                    style='color:#aa7722;font-style:italic;'>o</span><span
                    style='color:#aa6622;font-style:italic;'>e</span><span
                    style='color:#996633;font-style:italic;'>r&nbsp;:egg:</span></a></td>
        <td>55</td>
        <td>2788.733</td>
        <td>166.455</td>
    </tr>
    <tr>
        <td>26</td>
        <td><a href=players.php?pid=20334&edition=5>:pikachus:</a></td>
        <td>54</td>
        <td>2895.893</td>
        <td>133.185</td>
    </tr>
    <tr>
        <td>27</td>
        <td><a href=players.php?pid=20685&edition=5><span style='color:#ff9900;'>Bl</span><span
                    style='color:#ffffff;'>urs</span></a></td>
        <td>54</td>
        <td>2904.413</td>
        <td>145.019</td>
    </tr>
    <tr>
        <td>28</td>
        <td><a href=players.php?pid=6789&edition=5><span style='color:#ff9900;'>S</span><span
                    style='color:#ffaa22;'>a</span><span style='color:#ffbb44;'>m</span><span
                    style='color:#ffbb66;'>i</span><span style='color:#ffcc88;'>f</span><span
                    style='color:#ffdd99;'>y</span><span style='color:#ffeebb;'>i</span><span
                    style='color:#ffeedd;'>n</span><span style='color:#ffffff;'>g</span></a></td>
        <td>54</td>
        <td>2936.453</td>
        <td>189.519</td>
    </tr>
    <tr>
        <td>29</td>
        <td><a href=players.php?pid=6960&edition=5><span style='color:#bb77ff;'>Show</span><span
                    style='color:#ffffff;'>love:peepolove:</span></a></td>
        <td>53</td>
        <td>3018.200</td>
        <td>120.094</td>
    </tr>
    <tr>
        <td>30</td>
        <td><a href=players.php?pid=31517&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>Begy</span></a></td>
        <td>53</td>
        <td>3034.627</td>
        <td>143.340</td>
    </tr>
    <tr>
        <td>31</td>
        <td><a href=players.php?pid=29394&edition=5><span style='color:#33aa55;'>glue</span><span
                    style='color:#ffffff;'>sniffah</span></a></td>
        <td>53</td>
        <td>3048.840</td>
        <td>163.453</td>
    </tr>
    <tr>
        <td>32</td>
        <td><a href=players.php?pid=34083&edition=5>banktm</a></td>
        <td>52</td>
        <td>3180.173</td>
        <td>163.712</td>
    </tr>
    <tr>
        <td>33</td>
        <td><a href=players.php?pid=21841&edition=5>Ilnapi</a></td>
        <td>52</td>
        <td>3186.813</td>
        <td>173.288</td>
    </tr>
    <tr>
        <td>34</td>
        <td><a href=players.php?pid=6115&edition=5><span style='color:#ff9900;'>yaka</span><span
                    style='color:#ffffff;'>lelo&nbsp;</span><span style='color:#ff9900;'>yaka</span><span
                    style='color:#ffffff;'>lelo</span></a></td>
        <td>52</td>
        <td>3192.253</td>
        <td>181.135</td>
    </tr>
    <tr>
        <td>35</td>
        <td><a href=players.php?pid=6343&edition=5><span style='color:#33aa55;'>nova</span><span
                    style='color:#ffffff;'>stxr</span></a></td>
        <td>51</td>
        <td>3310.987</td>
        <td>163.216</td>
    </tr>
    <tr>
        <td>36</td>
        <td><a href=players.php?pid=14744&edition=5>:fatass:</a></td>
        <td>51</td>
        <td>3331.627</td>
        <td>193.569</td>
    </tr>
    <tr>
        <td>37</td>
        <td><a href=players.php?pid=7180&edition=5><span style='color:#ffffff;'>bren</span><span
                    style='color:#ffcc33;'>!</span></a></td>
        <td>50</td>
        <td>3422.200</td>
        <td>133.300</td>
    </tr>
    <tr>
        <td>38</td>
        <td><a href=players.php?pid=1710&edition=5><span style='color:#ffffff;font-style:italic;'>&raquo;</span><span
                    style='color:#99ffff;font-style:italic;'>エ</span><span
                    style='color:#66ffff;font-style:italic;'>c</span><span
                    style='color:#33ffff;font-style:italic;'>e</span><span
                    style='color:#000000;font-style:italic;'>.</span></a></td>
        <td>50</td>
        <td>3436.320</td>
        <td>154.480</td>
    </tr>
    <tr>
        <td>39</td>
        <td><a href=players.php?pid=890&edition=5>nonick</a></td>
        <td>50</td>
        <td>3445.160</td>
        <td>167.740</td>
    </tr>
    <tr>
        <td>40</td>
        <td><a href=players.php?pid=24747&edition=5><span style='color:#ff9900;'>save&nbsp;</span><span
                    style='color:#ffffff;'>me</span></a></td>
        <td>49</td>
        <td>3526.907</td>
        <td>92.204</td>
    </tr>
    <tr>
        <td>41</td>
        <td><a href=players.php?pid=22276&edition=5><span style='color:#ff9900;'>B</span><span
                    style='color:#ffffff;'>ye</span></a></td>
        <td>49</td>
        <td>3573.240</td>
        <td>163.122</td>
    </tr>
    <tr>
        <td>42</td>
        <td><a href=players.php?pid=9745&edition=5><span style='color:#ff9900;'>Ja</span><span
                    style='color:#ffaa00;'>nVa</span><span style='color:#ffbb00;'>n8e</span><span
                    style='color:#ffcc00;'>rn</span></a></td>
        <td>49</td>
        <td>3573.240</td>
        <td>163.122</td>
    </tr>
    <tr>
        <td>43</td>
        <td><a href=players.php?pid=1294&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>Tarpor</span></a></td>
        <td>49</td>
        <td>3578.613</td>
        <td>171.347</td>
    </tr>
    <tr>
        <td>44</td>
        <td><a href=players.php?pid=28536&edition=5><span style='color:#0000ff;font-style:italic;'>P</span><span
                    style='color:#2222ff;font-style:italic;'>r</span>0<span
                    style='color:#6666ff;font-style:italic;'>x</span><span
                    style='color:#8888ff;font-style:italic;'>i</span><span
                    style='color:#9999ff;font-style:italic;'>m</span><span
                    style='color:#bbbbff;font-style:italic;'>ate</span></a></td>
        <td>49</td>
        <td>3595.987</td>
        <td>197.939</td>
    </tr>
    <tr>
        <td>45</td>
        <td><a href=players.php?pid=7320&edition=5><span style='color:#33aa55;font-style:italic;'>&dagger;</span><span
                    style='color:#ffffff;font-style:italic;'>и&dagger;</span></a></td>
        <td>48</td>
        <td>3683.187</td>
        <td>129.979</td>
    </tr>
    <tr>
        <td>46</td>
        <td><a href=players.php?pid=369&edition=5>slujshshsksuysh13</a></td>
        <td>48</td>
        <td>3695.987</td>
        <td>149.979</td>
    </tr>
    <tr>
        <td>47</td>
        <td><a href=players.php?pid=6271&edition=5><span style='color:#ffcc99;font-style:italic;'>w</span><span
                    style='color:#ffddbb;font-style:italic;'>a</span><span
                    style='color:#ffeecc;font-style:italic;'>l</span><span
                    style='color:#ffeeee;font-style:italic;'>l</span><span
                    style='color:#ffffff;font-style:italic;'>y</span></a></td>
        <td>48</td>
        <td>3704.440</td>
        <td>163.188</td>
    </tr>
    <tr>
        <td>48</td>
        <td><a href=players.php?pid=23782&edition=5><span style='color:#ff0000;'>Foon</span><span
                    style='color:#ffffff;'>eses</span></a></td>
        <td>47</td>
        <td>3838.347</td>
        <td>167.574</td>
    </tr>
    <tr>
        <td>49</td>
        <td><a href=players.php?pid=10001&edition=5>kcaj</a></td>
        <td>47</td>
        <td>3849.733</td>
        <td>185.745</td>
    </tr>
    <tr>
        <td>50</td>
        <td><a href=players.php?pid=53951&edition=5>spemeri</a></td>
        <td>47</td>
        <td>3851.427</td>
        <td>188.447</td>
    </tr>
    <tr>
        <td>51</td>
        <td><a href=players.php?pid=26319&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='color:#99ccff;font-style:italic;'>Snappie</span></a></td>
        <td>46</td>
        <td>3952.000</td>
        <td>139.130</td>
    </tr>
    <tr>
        <td>52</td>
        <td><a href=players.php?pid=166&edition=5><span style='color:#00ffff;'>S</span><span
                    style='color:#11ccff;'>h</span><span style='color:#1199ff;'>i</span><span
                    style='color:#2266ff;'>e</span><span style='color:#2233ff;'>l</span><span
                    style='color:#3300ff;'>d</span><span style='color:#3300ff;'>b</span><span
                    style='color:#4400ee;'>a</span><span style='color:#5500ee;'>n</span><span
                    style='color:#7700dd;'>d</span><span style='color:#8800dd;'>i</span><span
                    style='color:#9900cc;'>t</span></a></td>
        <td>46</td>
        <td>3973.733</td>
        <td>174.565</td>
    </tr>
    <tr>
        <td>53</td>
        <td><a href=players.php?pid=562&edition=5>Simi_TM</a></td>
        <td>46</td>
        <td>3989.013</td>
        <td>199.478</td>
    </tr>
    <tr>
        <td>54</td>
        <td><a href=players.php?pid=23624&edition=5><span style='color:#000000;'>monka&nbsp;</span><span
                    style='color:#ffffff;'>|&nbsp;caloz</span></a></td>
        <td>46</td>
        <td>3999.027</td>
        <td>215.804</td>
    </tr>
    <tr>
        <td>55</td>
        <td><a href=players.php?pid=598&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>Jan</span></a></td>
        <td>45</td>
        <td>4121.133</td>
        <td>201.889</td>
    </tr>
    <tr>
        <td>56</td>
        <td><a href=players.php?pid=8903&edition=5>DavidH</a></td>
        <td>44</td>
        <td>4233.133</td>
        <td>170.114</td>
    </tr>
    <tr>
        <td>57</td>
        <td><a href=players.php?pid=62852&edition=5>Loap&nbsp;&laquo;&nbsp;т&sup3;</a></td>
        <td>44</td>
        <td>4257.253</td>
        <td>211.227</td>
    </tr>
    <tr>
        <td>58</td>
        <td><a href=players.php?pid=40633&edition=5><span style='color:#aa9911;'>🏃</span><span
                    style='color:#112299;'>P</span><span style='color:#112288;'>e</span><span
                    style='color:#2288aa;'>&euml;</span><span style='color:#11aa33;'>w</span></a></td>
        <td>44</td>
        <td>4257.627</td>
        <td>211.864</td>
    </tr>
    <tr>
        <td>59</td>
        <td><a href=players.php?pid=3913&edition=5><span style='color:#ff9900;'>An</span><span
                    style='color:#ffffff;'>vil</span></a></td>
        <td>44</td>
        <td>4264.480</td>
        <td>223.545</td>
    </tr>
    <tr>
        <td>60</td>
        <td><a href=players.php?pid=34205&edition=5><span style='color:#ff9900;'>でech</span><span
                    style='color:#ffffff;'>.str</span><span style='color:#ff9900;'>ツ</span></a></td>
        <td>43</td>
        <td>4352.360</td>
        <td>149.465</td>
    </tr>
    <tr>
        <td>61</td>
        <td><a href=players.php?pid=8820&edition=5>Kaulushaikara</a></td>
        <td>43</td>
        <td>4352.733</td>
        <td>150.116</td>
    </tr>
    <tr>
        <td>62</td>
        <td><a href=players.php?pid=2915&edition=5><span style='color:#aaddee;font-style:italic;'>saucey</span></a></td>
        <td>43</td>
        <td>4355.307</td>
        <td>154.605</td>
    </tr>
    <tr>
        <td>63</td>
        <td><a href=players.php?pid=34883&edition=5><span style='color:#33aa55;font-weight:bold;'>Sch</span><span
                    style='color:#ffffff;font-weight:bold;'>meak&nbsp;:cool:</span></a></td>
        <td>43</td>
        <td>4372.480</td>
        <td>184.558</td>
    </tr>
    <tr>
        <td>64</td>
        <td><a href=players.php?pid=23855&edition=5>PuWWa</a></td>
        <td>43</td>
        <td>4373.853</td>
        <td>186.953</td>
    </tr>
    <tr>
        <td>65</td>
        <td><a href=players.php?pid=12000&edition=5><span style='color:#77ddff;'>g</span><span
                    style='color:#ffbbcc;'>a</span><span style='color:#ffffff;'>z</span><span
                    style='color:#ffbbcc;'>z</span><span style='color:#77ddff;'>i&nbsp;:smirkcat:</span></a></td>
        <td>43</td>
        <td>4392.720</td>
        <td>219.860</td>
    </tr>
    <tr>
        <td>66</td>
        <td><a href=players.php?pid=36437&edition=5><span style='color:#0033ff;'>Pa</span><span
                    style='color:#ffffff;'>to</span><span style='color:#ff0000;'>ch:e:</span></a></td>
        <td>42</td>
        <td>4479.413</td>
        <td>141.810</td>
    </tr>
    <tr>
        <td>67</td>
        <td><a href=players.php?pid=21924&edition=5><span style='color:#3333cc;'>Y</span><span
                    style='color:#2222dd;'>ou</span><span style='color:#1111ee;'>rO</span><span
                    style='color:#0000ff;'>n</span><span style='color:#0000ff;'>l</span><span
                    style='color:#0000ee;'>yH</span><span style='color:#0000dd;'>op</span><span
                    style='color:#0000cc;'>e</span></a></td>
        <td>42</td>
        <td>4510.267</td>
        <td>196.905</td>
    </tr>
    <tr>
        <td>68</td>
        <td><a href=players.php?pid=6495&edition=5>Chow</a></td>
        <td>42</td>
        <td>4510.707</td>
        <td>197.690</td>
    </tr>
    <tr>
        <td>69</td>
        <td><a href=players.php?pid=26684&edition=5><span style='color:#33aa55;font-style:italic;'>dj</span><span
                    style='color:#ffffff;font-style:italic;'>inn</span></a></td>
        <td>42</td>
        <td>4521.987</td>
        <td>217.833</td>
    </tr>
    <tr>
        <td>70</td>
        <td><a href=players.php?pid=4377&edition=5><span style='color:#ff9900;'>xDr</span><span
                    style='color:#ffffff;'>aphi</span></a></td>
        <td>41</td>
        <td>4617.373</td>
        <td>153.732</td>
    </tr>
    <tr>
        <td>71</td>
        <td><a href=players.php?pid=41525&edition=5>Superfly.</a></td>
        <td>41</td>
        <td>4619.600</td>
        <td>157.805</td>
    </tr>
    <tr>
        <td>72</td>
        <td><a href=players.php?pid=8350&edition=5><span style='color:#ff9900;'>Brau</span><span
                    style='color:#ffffff;'>sen</span></a></td>
        <td>41</td>
        <td>4641.627</td>
        <td>198.098</td>
    </tr>
    <tr>
        <td>73</td>
        <td><a href=players.php?pid=33721&edition=5><span style='color:#ffffff;'>Dzamal&nbsp;</span><span
                    style='color:#22bbff;'>&laquo;&nbsp;</span><span style='color:#ffffff;'>т</span><span
                    style='color:#22bbff;'>&sup3;</span></a></td>
        <td>41</td>
        <td>4644.707</td>
        <td>203.732</td>
    </tr>
    <tr>
        <td>74</td>
        <td><a href=players.php?pid=8779&edition=5><span style='color:#33aa55;'>&mu;</span><span
                    style='color:#33aa55;'>&scaron;</span><span style='color:#33aa55;'>ţ</span><span
                    style='color:#33aa55;'>г</span><span style='color:#ffffff;'>ĵ</span><span
                    style='color:#ffffff;'>&oslash;</span><span style='color:#ffffff;'>ĥ</span><span
                    style='color:#ffffff;'>и</span></a></td>
        <td>41</td>
        <td>4652.040</td>
        <td>217.146</td>
    </tr>
    <tr>
        <td>75</td>
        <td><a href=players.php?pid=6245&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Leadec</span></a></td>
        <td>41</td>
        <td>4668.293</td>
        <td>246.878</td>
    </tr>
    <tr>
        <td>76</td>
        <td><a href=players.php?pid=50780&edition=5><span style='color:#005588;'>&ETH;</span><span
                    style='color:#005588;'>j</span><span style='color:#004477;'>s</span><span
                    style='color:#004477;'>&acirc;</span><span style='color:#004477;'>&uuml;</span><span
                    style='color:#004466;'>&ccedil;</span><span style='color:#004466;'>&egrave;</span><span
                    style='color:#114477;'>&szlig;</span><span style='color:#115588;'>&auml;</span><span
                    style='color:#226688;'>&ugrave;</span><span style='color:#336699;'>s</span><span
                    style='color:#3377aa;'>s</span></a></td>
        <td>40</td>
        <td>4777.160</td>
        <td>207.175</td>
    </tr>
    <tr>
        <td>77</td>
        <td><a href=players.php?pid=38&edition=5><span style='color:#ffffff;'>b</span><span
                    style='color:#ccffee;'>o</span><span style='color:#99ffcc;'>o</span><span
                    style='color:#66ffbb;'>s</span><span style='color:#33ff99;'>ti</span></a></td>
        <td>40</td>
        <td>4786.653</td>
        <td>224.975</td>
    </tr>
    <tr>
        <td>78</td>
        <td><a href=players.php?pid=24955&edition=5>golden&nbsp;:smirkcat:</a></td>
        <td>40</td>
        <td>4793.053</td>
        <td>236.975</td>
    </tr>
    <tr>
        <td>79</td>
        <td><a href=players.php?pid=41059&edition=5><span style='color:#ff8800;'>Altrox</span></a></td>
        <td>40</td>
        <td>4796.733</td>
        <td>243.875</td>
    </tr>
    <tr>
        <td>80</td>
        <td><a href=players.php?pid=27610&edition=5><span style='color:#ff9900;'>honne</span><span
                    style='color:#ffffff;'>pon</span></a></td>
        <td>40</td>
        <td>4830.707</td>
        <td>307.575</td>
    </tr>
    <tr>
        <td>81</td>
        <td><a href=players.php?pid=26396&edition=5>Its_Cam__</a></td>
        <td>39</td>
        <td>4884.160</td>
        <td>161.846</td>
    </tr>
    <tr>
        <td>82</td>
        <td><a href=players.php?pid=64&edition=5>Tres__</a></td>
        <td>39</td>
        <td>4909.587</td>
        <td>210.744</td>
    </tr>
    <tr>
        <td>83</td>
        <td><a href=players.php?pid=8809&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>dazzzyy</span></a></td>
        <td>39</td>
        <td>4917.280</td>
        <td>225.538</td>
    </tr>
    <tr>
        <td>84</td>
        <td><a href=players.php?pid=2838&edition=5>ShaDenis_</a></td>
        <td>38</td>
        <td>5019.400</td>
        <td>169.868</td>
    </tr>
    <tr>
        <td>85</td>
        <td><a href=players.php?pid=957&edition=5><span style='color:#ff9900;'>ABC</span><span
                    style='color:#ffffff;'>jay</span></a></td>
        <td>38</td>
        <td>5025.707</td>
        <td>182.316</td>
    </tr>
    <tr>
        <td>86</td>
        <td><a href=players.php?pid=32303&edition=5><span style='color:#dd0000;font-style:italic;'>&rho;</span><span
                    style='color:#cc0000;font-style:italic;'>u</span><span
                    style='color:#aa0000;font-style:italic;'>l</span><span
                    style='color:#990000;font-style:italic;'>s</span><span
                    style='color:#880000;font-style:italic;'>e</span><span
                    style='color:#000000;font-style:italic;'>.</span><span
                    style='color:#ffffff;font-style:italic;'>zah</span></a></td>
        <td>38</td>
        <td>5030.120</td>
        <td>191.026</td>
    </tr>
    <tr>
        <td>87</td>
        <td><a href=players.php?pid=8345&edition=5>:hmm:</a></td>
        <td>38</td>
        <td>5031.013</td>
        <td>192.789</td>
    </tr>
    <tr>
        <td>88</td>
        <td><a href=players.php?pid=14387&edition=5><span style='font-weight:bold;'>&nbsp;</span><span
                    style='font-weight:bold;'>&nbsp;JNIC</span></a></td>
        <td>38</td>
        <td>5053.547</td>
        <td>237.263</td>
    </tr>
    <tr>
        <td>89</td>
        <td><a href=players.php?pid=67408&edition=5>Fey.-</a></td>
        <td>37</td>
        <td>5166.520</td>
        <td>202.405</td>
    </tr>
    <tr>
        <td>90</td>
        <td><a href=players.php?pid=51850&edition=5><span style='color:#331133;font-weight:bold;'>S</span><span
                    style='color:#331133;'>aqqeee</span></a></td>
        <td>37</td>
        <td>5175.467</td>
        <td>220.541</td>
    </tr>
    <tr>
        <td>91</td>
        <td><a href=players.php?pid=52336&edition=5><span style='color:#33aa55;'>Tou</span><span
                    style='color:#ffffff;'>can</span></a></td>
        <td>37</td>
        <td>5180.133</td>
        <td>230.000</td>
    </tr>
    <tr>
        <td>92</td>
        <td><a href=players.php?pid=15767&edition=5>[<span style='color:#cc00ff;'>T</span>.TV]&nbsp;<span
                    style='color:#ff0099;'>R</span><span style='color:#ee22aa;'>a</span><span
                    style='color:#cc44bb;'>f</span><span style='color:#bb66cc;'>T</span><span
                    style='color:#aa99cc;'>o</span><span style='color:#99bbdd;'>r</span><span
                    style='color:#77ddee;'>T</span><span style='color:#66ffff;'>V</span></a></td>
        <td>37</td>
        <td>5184.373</td>
        <td>238.595</td>
    </tr>
    <tr>
        <td>93</td>
        <td><a href=players.php?pid=6852&edition=5><span style='color:#ffffff;'>D</span><span
                    style='color:#eeeeee;'>ı</span><span style='color:#dddddd;'>в</span><span
                    style='color:#cccccc;'>&epsilon;</span></a></td>
        <td>37</td>
        <td>5185.200</td>
        <td>240.270</td>
    </tr>
    <tr>
        <td>94</td>
        <td><a href=players.php?pid=12154&edition=5><span style='color:#ff0000;'>L</span><span
                    style='color:#ee0000;'>a</span><span style='color:#dd0000;'>r</span><span
                    style='color:#cc0000;'>s</span><span style='color:#ffeeee;'>tm</span></a></td>
        <td>36</td>
        <td>5286.107</td>
        <td>179.389</td>
    </tr>
    <tr>
        <td>95</td>
        <td><a href=players.php?pid=616&edition=5><span style='color:#0000cc;'>Ł</span><span
                    style='color:#0011dd;'>&sigma;</span><span style='color:#0022dd;'>&alpha;</span><span
                    style='color:#0033ee;'>ȡ</span><span style='color:#0044ee;'>ϊ</span><span
                    style='color:#0055ff;'>ก</span><span style='color:#0066ff;'>ǥ&nbsp;</span><span
                    style='color:#66ffff;'>々&nbsp;</span><span style='color:#ffffff;'>&not;&nbsp;</span><span
                    style='color:#ffcc00;'>Flow</span></a></td>
        <td>36</td>
        <td>5304.840</td>
        <td>218.417</td>
    </tr>
    <tr>
        <td>96</td>
        <td><a href=players.php?pid=21777&edition=5>skr<span style='color:#ff9900;'>e</span><span
                    style='color:#ffffff;'>d</span></a></td>
        <td>36</td>
        <td>5311.507</td>
        <td>232.306</td>
    </tr>
    <tr>
        <td>97</td>
        <td><a href=players.php?pid=33694&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>bLurious</span></a>
        </td>
        <td>36</td>
        <td>5323.613</td>
        <td>257.528</td>
    </tr>
    <tr>
        <td>98</td>
        <td><a href=players.php?pid=1828&edition=5><span style='color:#006633;font-style:italic;'>&rho;</span><span
                    style='color:#008855;font-style:italic;'>&upsilon;</span><span
                    style='color:#009966;font-style:italic;'>І</span><span
                    style='color:#009966;font-style:italic;'>ѕ</span><span
                    style='color:#00cc99;font-style:italic;'>е</span><span
                    style='color:#000000;font-style:italic;'>.</span><span
                    style='color:#ffffff;font-style:italic;'>Mammouth</span></a></td>
        <td>35</td>
        <td>5414.787</td>
        <td>174.543</td>
    </tr>
    <tr>
        <td>99</td>
        <td><a href=players.php?pid=7790&edition=5><span style='color:#ffffff;'>ka</span><span
                    style='color:#33aa55;'>w</span><span style='color:#ffffff;'>ati</span></a></td>
        <td>35</td>
        <td>5435.667</td>
        <td>219.286</td>
    </tr>
    <tr>
        <td>100</td>
        <td><a href=players.php?pid=6451&edition=5><span style='color:#ff9900;font-style:italic;'>Cox</span><span
                    style='color:#ffffff;font-style:italic;'>in</span></a></td>
        <td>35</td>
        <td>5440.000</td>
        <td>228.571</td>
    </tr>
    <tr>
        <td>101</td>
        <td><a href=players.php?pid=40990&edition=5>Eddy!</a></td>
        <td>35</td>
        <td>5440.747</td>
        <td>230.171</td>
    </tr>
    <tr>
        <td>102</td>
        <td><a href=players.php?pid=31063&edition=5>Faze&nbsp;balls&nbsp;:gigachad:</a></td>
        <td>35</td>
        <td>5445.680</td>
        <td>240.743</td>
    </tr>
    <tr>
        <td>103</td>
        <td><a href=players.php?pid=46139&edition=5>Deisism</a></td>
        <td>35</td>
        <td>5477.280</td>
        <td>308.457</td>
    </tr>
    <tr>
        <td>104</td>
        <td><a href=players.php?pid=51747&edition=5><span style='color:#ff0000;'>žĘ</span><span
                    style='color:#ff1100;'>Ŝţ丫</span><span style='color:#ff2200;'>&nbsp;-&nbsp;エ</span><span
                    style='color:#ff3300;'>NҒ&nbsp;:cool:</span></a></td>
        <td>34</td>
        <td>5531.840</td>
        <td>143.765</td>
    </tr>
    <tr>
        <td>105</td>
        <td><a href=players.php?pid=6437&edition=5>viiru&nbsp;<span style='color:#ffcc22;'>:</span><span
                    style='color:#ff9933;'>s</span><span style='color:#ee6633;'>m</span><span
                    style='color:#ee6633;'>i</span><span style='color:#ee5533;'>r</span><span
                    style='color:#ee3333;'>k</span><span style='color:#cc1177;'>c</span><span
                    style='color:#992277;'>a</span><span style='color:#662266;'>t</span><span
                    style='color:#333366;'>:</span></a></td>
        <td>34</td>
        <td>5543.747</td>
        <td>170.029</td>
    </tr>
    <tr>
        <td>106</td>
        <td><a href=players.php?pid=25923&edition=5><span style='color:#ff9900;'>Ar</span><span
                    style='color:#ffffff;'>ne..</span></a></td>
        <td>34</td>
        <td>5546.187</td>
        <td>175.412</td>
    </tr>
    <tr>
        <td>107</td>
        <td><a href=players.php?pid=8015&edition=5><span style='color:#ff9900;font-style:italic;'>Tallie</span><span
                    style='color:#ffffff;font-style:italic;'>bird</span></a></td>
        <td>34</td>
        <td>5549.293</td>
        <td>182.265</td>
    </tr>
    <tr>
        <td>108</td>
        <td><a href=players.php?pid=6434&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#00ff00;font-style:italic;'>Jean-Ren&eacute;&nbsp;</span></a></td>
        <td>34</td>
        <td>5565.147</td>
        <td>217.235</td>
    </tr>
    <tr>
        <td>109</td>
        <td><a href=players.php?pid=14794&edition=5><span style='color:#cc0000;'>D</span><span
                    style='color:#ffffff;'>iii</span><span style='color:#cc0000;'>Z</span><span
                    style='color:#ffffff;'>iii</span></a></td>
        <td>34</td>
        <td>5571.387</td>
        <td>231.000</td>
    </tr>
    <tr>
        <td>110</td>
        <td><a href=players.php?pid=18469&edition=5>:owo:<span style='color:#44ddff;'>&nbsp;</span><span
                    style='color:#55ccff;'>m</span><span style='color:#66ccff;'>b</span><span
                    style='color:#66ccff;'>a</span><span style='color:#77ccdd;'>t</span><span
                    style='color:#88ddcc;'>l</span><span style='color:#99ddaa;'>o</span><span
                    style='color:#99ee88;'>v</span><span style='color:#aaee66;'>e</span><span
                    style='color:#bbff55;'>r</span><span style='color:#ccff33;'>1</span></a></td>
        <td>34</td>
        <td>5571.680</td>
        <td>231.647</td>
    </tr>
    <tr>
        <td>111</td>
        <td><a href=players.php?pid=11370&edition=5>Rubbie</a></td>
        <td>34</td>
        <td>5587.053</td>
        <td>265.559</td>
    </tr>
    <tr>
        <td>112</td>
        <td><a href=players.php?pid=17166&edition=5><span style='color:#550000;font-weight:bold;'>Ǥ</span><span
                    style='color:#770000;font-weight:bold;'>&sigma;</span><span
                    style='color:#990000;font-weight:bold;'>l</span><span
                    style='color:#bb0000;font-weight:bold;'>i</span><span
                    style='color:#dd0000;font-weight:bold;'>&sigma;</span></a></td>
        <td>34</td>
        <td>5589.240</td>
        <td>270.382</td>
    </tr>
    <tr>
        <td>113</td>
        <td><a href=players.php?pid=25139&edition=5>ThisTheSandstorm</a></td>
        <td>33</td>
        <td>5667.813</td>
        <td>154.121</td>
    </tr>
    <tr>
        <td>114</td>
        <td><a href=players.php?pid=19453&edition=5><span style='color:#9900ff;font-style:italic;'>V</span><span
                    style='color:#aa00ff;font-style:italic;'>e</span><span
                    style='color:#bb00ff;font-style:italic;'>r</span><span
                    style='color:#cc00ff;font-style:italic;'>t</span><span
                    style='color:#cc00ff;font-style:italic;'>u</span><span
                    style='color:#bb00ff;font-style:italic;'>n</span><span
                    style='color:#ffffff;font-style:italic;'>!&nbsp;</span></a></td>
        <td>33</td>
        <td>5678.787</td>
        <td>179.061</td>
    </tr>
    <tr>
        <td>115</td>
        <td><a href=players.php?pid=23137&edition=5>the&nbsp;rat,</a></td>
        <td>33</td>
        <td>5707.387</td>
        <td>244.061</td>
    </tr>
    <tr>
        <td>116</td>
        <td><a href=players.php?pid=35610&edition=5><span style='color:#ff00ff;'>PlatinumZ:owo:rb</span></a></td>
        <td>33</td>
        <td>5724.547</td>
        <td>283.061</td>
    </tr>
    <tr>
        <td>117</td>
        <td><a href=players.php?pid=11683&edition=5><span style='color:#ff9933;'>Scoop&nbsp;:pepeJAM:&nbsp;</span><span
                    style='color:#33bb88;'>CHROMAKOPIA&nbsp;:pepeJAM:</span></a></td>
        <td>32</td>
        <td>5821.813</td>
        <td>207.375</td>
    </tr>
    <tr>
        <td>118</td>
        <td><a href=players.php?pid=848&edition=5><span style='color:#cc3300;'>m</span><span
                    style='color:#dd2244;'>a</span><span style='color:#ee1188;'>x</span><span
                    style='color:#ff00cc;'>m</span><span style='color:#ff00cc;'>a</span><span
                    style='color:#aa11dd;'>d</span><span style='color:#5522ee;'>4</span><span
                    style='color:#0033ff;'>6</span></a></td>
        <td>32</td>
        <td>5823.080</td>
        <td>210.344</td>
    </tr>
    <tr>
        <td>119</td>
        <td><a href=players.php?pid=50460&edition=5><span style='color:#ff0000;'>Ruhtr4</span></a></td>
        <td>32</td>
        <td>5824.813</td>
        <td>214.406</td>
    </tr>
    <tr>
        <td>120</td>
        <td><a href=players.php?pid=32273&edition=5><span style='color:#ff9900;'>G</span><span
                    style='color:#ffbb44;'>u</span><span style='color:#ffcc88;'>i</span><span
                    style='color:#ffeebb;'>z</span><span style='color:#ffffff;'>i</span></a></td>
        <td>32</td>
        <td>5832.920</td>
        <td>233.406</td>
    </tr>
    <tr>
        <td>121</td>
        <td><a href=players.php?pid=12002&edition=5>CyberMaxdk59</a></td>
        <td>32</td>
        <td>5838.880</td>
        <td>247.375</td>
    </tr>
    <tr>
        <td>122</td>
        <td><a href=players.php?pid=8650&edition=5>Light.TM</a></td>
        <td>32</td>
        <td>5840.893</td>
        <td>252.094</td>
    </tr>
    <tr>
        <td>123</td>
        <td><a href=players.php?pid=12874&edition=5><span style='color:#ff9900;'>Omega</span><span
                    style='color:#ffffff;'>status</span></a></td>
        <td>32</td>
        <td>5848.200</td>
        <td>269.219</td>
    </tr>
    <tr>
        <td>124</td>
        <td><a href=players.php?pid=2396&edition=5><span style='color:#ffff00;font-style:italic;'>ฑ</span><span
                    style='color:#cc0000;font-style:italic;'>o-s</span><span
                    style='color:#ffff00;font-style:italic;'>ƺ</span><span
                    style='color:#cc0000;font-style:italic;'>nse</span><span
                    style='color:#ffff00;font-style:italic;'>ॐ</span></a></td>
        <td>32</td>
        <td>5853.133</td>
        <td>280.781</td>
    </tr>
    <tr>
        <td>125</td>
        <td><a href=players.php?pid=63176&edition=5><span
                    style='color:#99ffcc;font-style:italic;'>v&aelig;sh</span><span
                    style='color:#000000;font-style:italic;'>.</span></a></td>
        <td>31</td>
        <td>5949.253</td>
        <td>199.806</td>
    </tr>
    <tr>
        <td>126</td>
        <td><a href=players.php?pid=62606&edition=5>tricmania</a></td>
        <td>31</td>
        <td>5950.547</td>
        <td>202.935</td>
    </tr>
    <tr>
        <td>127</td>
        <td><a href=players.php?pid=22739&edition=5>ThiccBoi9120</a></td>
        <td>31</td>
        <td>5961.067</td>
        <td>228.387</td>
    </tr>
    <tr>
        <td>128</td>
        <td><a href=players.php?pid=29551&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#33aa55;'>jyrt</span><span style='color:#ffffff;'>ope</span></a></td>
        <td>31</td>
        <td>5962.947</td>
        <td>232.935</td>
    </tr>
    <tr>
        <td>129</td>
        <td><a href=players.php?pid=32225&edition=5>Astranovae</a></td>
        <td>31</td>
        <td>5967.720</td>
        <td>244.484</td>
    </tr>
    <tr>
        <td>130</td>
        <td><a href=players.php?pid=30032&edition=5><span
                    style='letter-spacing: -0.1em;font-size:smaller'>specu.</span><span
                    style='color:#aaaaaa;font-weight:bold;'>&nbsp;/&nbsp;winterarc</span></a></td>
        <td>30</td>
        <td>6053.933</td>
        <td>134.833</td>
    </tr>
    <tr>
        <td>131</td>
        <td><a href=players.php?pid=37309&edition=5><span style='color:#ff9900;'>lego&nbsp;pie</span><span
                    style='color:#ffffff;'>ce&nbsp;46303</span></a></td>
        <td>30</td>
        <td>6078.080</td>
        <td>195.200</td>
    </tr>
    <tr>
        <td>132</td>
        <td><a href=players.php?pid=19&edition=5>CptSalmon</a></td>
        <td>30</td>
        <td>6078.187</td>
        <td>195.467</td>
    </tr>
    <tr>
        <td>133</td>
        <td><a href=players.php?pid=6406&edition=5><span style='color:#9933ff;'>K</span><span
                    style='color:#ffffff;'>re</span><span style='color:#9933ff;'>LL</span><span
                    style='color:#ffffff;'>e</span><span style='color:#9933ff;'>R</span></a></td>
        <td>30</td>
        <td>6081.467</td>
        <td>203.667</td>
    </tr>
    <tr>
        <td>134</td>
        <td><a href=players.php?pid=7280&edition=5><span style='color:#660000;'>R</span><span
                    style='color:#990000;'>&ouml;</span><span style='color:#cc0000;'>d</span><span
                    style='color:#ff0000;'>e</span><span style='color:#ff3366;'>r</span></a></td>
        <td>30</td>
        <td>6083.360</td>
        <td>208.400</td>
    </tr>
    <tr>
        <td>135</td>
        <td><a href=players.php?pid=62607&edition=5>mttap</a></td>
        <td>30</td>
        <td>6088.213</td>
        <td>220.533</td>
    </tr>
    <tr>
        <td>136</td>
        <td><a href=players.php?pid=66509&edition=5>[<span style='color:#ff0000;'>B</span><span
                    style='color:#ff5500;'>A</span><span style='color:#ffaa00;'>L</span><span
                    style='color:#ffff00;'>D</span>]DoBeVibin</a></td>
        <td>30</td>
        <td>6088.480</td>
        <td>221.200</td>
    </tr>
    <tr>
        <td>137</td>
        <td><a href=players.php?pid=31740&edition=5><span style='color:#33ff00;'>C</span><span
                    style='color:#77ff55;'>ђ</span><span style='color:#bbffaa;'>น</span><span
                    style='color:#ffffff;'>r</span><span style='color:#ffffff;'>г</span><span
                    style='color:#ffffaa;'>ơ</span><span style='color:#ffff55;'>3</span><span
                    style='color:#ffff00;'>6</span></a></td>
        <td>30</td>
        <td>6091.080</td>
        <td>227.700</td>
    </tr>
    <tr>
        <td>138</td>
        <td><a href=players.php?pid=975&edition=5>ZyzyKackyEnjoyer</a></td>
        <td>30</td>
        <td>6096.960</td>
        <td>242.400</td>
    </tr>
    <tr>
        <td>139</td>
        <td><a href=players.php?pid=24549&edition=5><span style='color:#33aa55;font-weight:bold;'>.</span><span
                    style='color:#660000;letter-spacing: -0.1em;font-size:smaller'>b</span><span
                    style='color:#bb0000;letter-spacing: -0.1em;font-size:smaller'>o</span><span
                    style='color:#ff0000;letter-spacing: -0.1em;font-size:smaller'>b</span><span
                    style='color:#ff0066;letter-spacing: -0.1em;font-size:smaller'>o</span></a></td>
        <td>30</td>
        <td>6098.960</td>
        <td>247.400</td>
    </tr>
    <tr>
        <td>140</td>
        <td><a href=players.php?pid=13753&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Otarrack</span></a></td>
        <td>30</td>
        <td>6100.547</td>
        <td>251.367</td>
    </tr>
    <tr>
        <td>141</td>
        <td><a href=players.php?pid=19630&edition=5>Evozer</a></td>
        <td>30</td>
        <td>6106.493</td>
        <td>266.233</td>
    </tr>
    <tr>
        <td>142</td>
        <td><a href=players.php?pid=62289&edition=5><span style='color:#000099;'>S</span><span
                    style='color:#1122aa;'>u</span><span style='color:#2244bb;'>p</span><span
                    style='color:#3366cc;'>r</span><span style='color:#4488dd;'>e</span><span
                    style='color:#55aaee;'>m</span><span style='color:#66ccff;'>e</span><span
                    style='color:#66ccff;'>o</span><span style='color:#77ddff;'>r</span><span
                    style='color:#77ddee;'>e</span><span style='color:#88eeee;'>o</span><span
                    style='color:#88eedd;'>1</span><span style='color:#99ffdd;'>2</span><span
                    style='color:#99ffcc;'>1</span></a></td>
        <td>30</td>
        <td>6111.107</td>
        <td>277.767</td>
    </tr>
    <tr>
        <td>143</td>
        <td><a href=players.php?pid=58011&edition=5><span style='color:#ffff33;'>P</span><span
                    style='color:#bbff77;'>l</span><span style='color:#77ffbb;'>a</span><span
                    style='color:#33ffff;'>s</span><span style='color:#33ffff;'>t</span><span
                    style='color:#2299ff;'>i</span><span style='color:#0033ff;'>c&nbsp;</span><span
                    style='color:#000000;'>:3</span></a></td>
        <td>30</td>
        <td>6143.800</td>
        <td>359.500</td>
    </tr>
    <tr>
        <td>144</td>
        <td><a href=players.php?pid=8013&edition=5><span style='color:#6633cc;'>:painsge:&nbsp;</span><span
                    style='color:#ff9900;'>Skill&nbsp;</span><span style='color:#ffffff;'>Issue</span></a></td>
        <td>29</td>
        <td>6193.827</td>
        <td>156.448</td>
    </tr>
    <tr>
        <td>145</td>
        <td><a href=players.php?pid=32362&edition=5><span style='color:#ff9900;font-weight:bold;'>JE</span><span
                    style='color:#ffffff;font-weight:bold;'>DI</span></a></td>
        <td>29</td>
        <td>6210.373</td>
        <td>199.241</td>
    </tr>
    <tr>
        <td>146</td>
        <td><a href=players.php?pid=7863&edition=5><span style='color:#ff9900;'>NBK</span><span
                    style='color:#ffffff;'>Mister</span><span style='color:#ff9900;'>x</span></a></td>
        <td>29</td>
        <td>6212.667</td>
        <td>205.172</td>
    </tr>
    <tr>
        <td>147</td>
        <td><a href=players.php?pid=11580&edition=5><span style='color:#ffffff;font-style:italic;'>VGCY.</span></a></td>
        <td>29</td>
        <td>6216.053</td>
        <td>213.931</td>
    </tr>
    <tr>
        <td>148</td>
        <td><a href=players.php?pid=9085&edition=5>ZarKuchen</a></td>
        <td>29</td>
        <td>6218.533</td>
        <td>220.345</td>
    </tr>
    <tr>
        <td>149</td>
        <td><a href=players.php?pid=33629&edition=5><span style='color:#ffffff;'>&alpha;&iota;г</span><span
                    style='color:#777777;'>&nbsp;ı|ı&nbsp;</span><span style='color:#aadddd;'>ch</span><span
                    style='color:#77dddd;'>ar</span><span style='color:#44dddd;'>les</span></a></td>
        <td>29</td>
        <td>6222.707</td>
        <td>231.138</td>
    </tr>
    <tr>
        <td>150</td>
        <td><a href=players.php?pid=13056&edition=5><span style='color:#ff0000;'>4</span><span
                    style='color:#cc0000;'>Y</span><span style='color:#990000;'>o</span><span
                    style='color:#660000;'>u</span><span style='color:#330000;'>r</span><span
                    style='color:#000000;'>N</span><span style='color:#000000;'>e</span><span
                    style='color:#000033;'>m</span><span style='color:#000066;'>e</span><span
                    style='color:#000099;'>s</span><span style='color:#0000cc;'>i</span><span
                    style='color:#0000ff;'>s</span></a></td>
        <td>29</td>
        <td>6227.973</td>
        <td>244.759</td>
    </tr>
    <tr>
        <td>151</td>
        <td><a href=players.php?pid=42&edition=5><span style='color:#ff00ff;'>В</span><span
                    style='color:#ff33cc;'>:omegalul::omegalul:</span><span style='color:#ff6699;'>ѕt</span><span
                    style='color:#ff9966;'>&iota;</span><span style='color:#ffcc33;'>ै</span><span
                    style='color:#ffff00;'>ѕ</span></a></td>
        <td>29</td>
        <td>6239.920</td>
        <td>275.655</td>
    </tr>
    <tr>
        <td>152</td>
        <td><a href=players.php?pid=32683&edition=5><span style='color:#ffffff;'>random</span><span
                    style='color:#11dd33;'>gloяp</span><span style='color:#ffffff;'>name</span></a></td>
        <td>29</td>
        <td>6261.933</td>
        <td>332.586</td>
    </tr>
    <tr>
        <td>153</td>
        <td><a href=players.php?pid=28612&edition=5><span style='color:#ff0066;'>ｱ</span><span
                    style='color:#ee3388;'>Ę</span><span style='color:#ee66aa;'>ד</span><span
                    style='color:#dd99bb;'>ｪ</span><span style='color:#ddccdd;'>イ</span><span
                    style='color:#ccffff;'>Ċ</span><span style='color:#ccffff;'>a</span><span
                    style='color:#ccffee;'>&Pi;</span><span style='color:#ccffcc;'>ｪ</span><span
                    style='color:#ccffbb;'>Ő</span><span style='color:#ccff99;'>й</span></a></td>
        <td>28</td>
        <td>6325.253</td>
        <td>156.929</td>
    </tr>
    <tr>
        <td>154</td>
        <td><a href=players.php?pid=62786&edition=5><span style='color:#000000;'>monka&nbsp;</span><span
                    style='color:#ffffff;'>|&nbsp;</span><span style='color:#000000;'>Ď</span><span
                    style='color:#440000;'>&Oslash;</span><span style='color:#880000;'>Ř</span><span
                    style='color:#cc0000;'>Ά</span></a></td>
        <td>28</td>
        <td>6353.373</td>
        <td>232.250</td>
    </tr>
    <tr>
        <td>155</td>
        <td><a href=players.php?pid=34822&edition=5><span style='color:#00ffff;'>Ŀ</span><span
                    style='color:#55ffff;'>น</span><span style='color:#aaffff;'>к</span><span
                    style='color:#ffffff;'>3</span></a></td>
        <td>28</td>
        <td>6357.773</td>
        <td>244.036</td>
    </tr>
    <tr>
        <td>156</td>
        <td><a href=players.php?pid=1602&edition=5><span style='color:#339900;'>toto&nbsp;:ezy:</span></a></td>
        <td>28</td>
        <td>6362.027</td>
        <td>255.429</td>
    </tr>
    <tr>
        <td>157</td>
        <td><a href=players.php?pid=34217&edition=5><span style='color:#33cccc;'>t</span><span
                    style='color:#44dddd;'>&omega;</span><span style='color:#55eeee;'>is</span><span
                    style='color:#66ffff;'>t</span></a></td>
        <td>28</td>
        <td>6367.533</td>
        <td>270.179</td>
    </tr>
    <tr>
        <td>158</td>
        <td><a href=players.php?pid=165&edition=5><span style='color:#006600;'>P</span><span
                    style='color:#558800;'>i</span><span style='color:#aabb00;'>z</span><span
                    style='color:#ffdd00;'>z</span><span style='color:#ffdd00;'>l</span><span
                    style='color:#aabb00;'>e</span><span style='color:#558800;'>K</span><span
                    style='color:#006600;'>R</span></a></td>
        <td>28</td>
        <td>6369.867</td>
        <td>276.429</td>
    </tr>
    <tr>
        <td>159</td>
        <td><a href=players.php?pid=11275&edition=5>KEKW2</a></td>
        <td>28</td>
        <td>6378.293</td>
        <td>299.000</td>
    </tr>
    <tr>
        <td>160</td>
        <td><a href=players.php?pid=10748&edition=5><span style='color:#ff3333;'>K</span><span
                    style='color:#dd5555;'>u</span><span style='color:#cc6666;'>k</span><span
                    style='color:#aa8888;'>k</span><span style='color:#88aaaa;'>e</span><span
                    style='color:#66cccc;'>t</span><span style='color:#55dddd;'>t</span><span
                    style='color:#33ffff;'>i</span></a></td>
        <td>28</td>
        <td>6379.213</td>
        <td>301.464</td>
    </tr>
    <tr>
        <td>161</td>
        <td><a href=players.php?pid=33469&edition=5><span style='color:#0033ff;'>J</span><span
                    style='color:#2233ff;'>P</span><span style='color:#3333ff;'>o</span><span
                    style='color:#5533ff;'>g</span><span style='color:#6633ff;'>g</span><span
                    style='color:#6633ff;'>e</span><span style='color:#8822ff;'>r</span><span
                    style='color:#9922ff;'>s</span><span style='color:#bb11ff;'>o</span><span
                    style='color:#cc00ff;'>n</span></a></td>
        <td>28</td>
        <td>6384.347</td>
        <td>315.214</td>
    </tr>
    <tr>
        <td>162</td>
        <td><a href=players.php?pid=3982&edition=5><span style='color:#000000;'>G</span><span
                    style='color:#330000;'>r</span><span style='color:#550000;'>a</span><span
                    style='color:#880000;'>v</span><span style='color:#aa0000;'>i</span><span
                    style='color:#dd0000;'>t</span><span style='color:#ff0000;'>y</span><span
                    style='color:#000000;font-style:italic;'>&nbsp;-&nbsp;</span><span
                    style='color:#ff0000;font-style:italic;'>T</span><span
                    style='color:#ff0022;font-style:italic;'>a</span><span
                    style='color:#ff0033;font-style:italic;'>&nbsp;</span><span
                    style='color:#ff0055;font-style:italic;'>D</span><span
                    style='color:#ff0066;font-style:italic;'>a</span></a></td>
        <td>27</td>
        <td>6490.347</td>
        <td>250.963</td>
    </tr>
    <tr>
        <td>163</td>
        <td><a href=players.php?pid=1136&edition=5><span style='color:#ff0077;'>E</span><span
                    style='color:#ffffff;'>C</span><span style='color:#ffdd11;'>L&nbsp;</span><span
                    style='color:#00ff00;'>D</span><span style='color:#00ff88;'>A</span><span
                    style='color:#00ffff;'>M</span></a></td>
        <td>27</td>
        <td>6493.347</td>
        <td>259.296</td>
    </tr>
    <tr>
        <td>164</td>
        <td><a href=players.php?pid=39926&edition=5><span style='color:#ff00ff;'>A</span><span
                    style='color:#ff33ff;'>s</span><span style='color:#ff55ff;'>t</span><span
                    style='color:#ff88ff;'>o</span><span style='color:#ffaaff;'>l</span><span
                    style='color:#ffddff;'>f</span><span style='color:#ffffff;'>o</span><span
                    style='color:#000000;'>D</span></a></td>
        <td>27</td>
        <td>6495.400</td>
        <td>265.000</td>
    </tr>
    <tr>
        <td>165</td>
        <td><a href=players.php?pid=20930&edition=5><span style='font-weight:bold;'>hayes:)</span></a></td>
        <td>27</td>
        <td>6496.653</td>
        <td>268.481</td>
    </tr>
    <tr>
        <td>166</td>
        <td><a href=players.php?pid=66186&edition=5>iiCatac<span style='color:#bb77ff;'>l</span><span
                    style='color:#ffffff;'>ysmic</span></a></td>
        <td>27</td>
        <td>6503.093</td>
        <td>286.370</td>
    </tr>
    <tr>
        <td>167</td>
        <td><a href=players.php?pid=32872&edition=5><span style='color:#0088dd;'>Thicc</span><span
                    style='color:#0066aa;'>Boy</span><span style='color:#005588;'>Lone</span></a></td>
        <td>27</td>
        <td>6521.240</td>
        <td>336.778</td>
    </tr>
    <tr>
        <td>168</td>
        <td><a href=players.php?pid=32577&edition=5><span style='color:#ffff33;'>p</span><span
                    style='color:#bbee66;'>r</span><span style='color:#88ee99;'>o</span><span
                    style='color:#44ddcc;'>b</span><span style='color:#00ccff;'>i</span><span
                    style='color:#00ccff;'>z</span><span style='color:#22ddaa;'>c</span><span
                    style='color:#44ee55;'>u</span><span style='color:#66ff00;'>s</span></a></td>
        <td>27</td>
        <td>6524.133</td>
        <td>344.815</td>
    </tr>
    <tr>
        <td>169</td>
        <td><a href=players.php?pid=7376&edition=5>Trumps&nbsp;Left&nbsp;Nut</a></td>
        <td>26</td>
        <td>6603.760</td>
        <td>203.154</td>
    </tr>
    <tr>
        <td>170</td>
        <td><a href=players.php?pid=3150&edition=5>Donkey</a></td>
        <td>26</td>
        <td>6609.240</td>
        <td>218.962</td>
    </tr>
    <tr>
        <td>171</td>
        <td><a href=players.php?pid=6470&edition=5><span style='color:#ff99ff;'>Aluji</span></a></td>
        <td>26</td>
        <td>6611.387</td>
        <td>225.154</td>
    </tr>
    <tr>
        <td>172</td>
        <td><a href=players.php?pid=10861&edition=5>miguel_n:owo:b</a></td>
        <td>26</td>
        <td>6616.773</td>
        <td>240.692</td>
    </tr>
    <tr>
        <td>173</td>
        <td><a href=players.php?pid=787&edition=5><span style='color:#ffffff;'>b</span><span
                    style='color:#ccffee;'>o</span><span style='color:#99ffcc;'>o</span><span
                    style='color:#66ffbb;'>s</span><span style='color:#33ff99;'>tmir</span></a></td>
        <td>26</td>
        <td>6617.067</td>
        <td>241.538</td>
    </tr>
    <tr>
        <td>174</td>
        <td><a href=players.php?pid=21838&edition=5>Hysteri<span style='color:#0000ff;'>k</span><span
                    style='color:#ffffff;'>T</span><span style='color:#ff0000;'>M</span></a></td>
        <td>26</td>
        <td>6620.413</td>
        <td>251.192</td>
    </tr>
    <tr>
        <td>175</td>
        <td><a href=players.php?pid=5128&edition=5><span style='color:#ffffff;'>b</span><span
                    style='color:#ddffff;'>o</span><span style='color:#bbffff;'>o</span><span
                    style='color:#99ffff;'>s</span><span style='color:#77ffff;'>t</span><span
                    style='color:#55ffff;'>s</span><span style='color:#33ffff;'>s</span><span
                    style='color:#33ffff;'>a</span><span style='color:#22eeff;'>ss</span><span
                    style='color:#11ddff;'>in</span><span style='color:#00ccff;'>e</span></a></td>
        <td>26</td>
        <td>6621.493</td>
        <td>254.308</td>
    </tr>
    <tr>
        <td>176</td>
        <td><a href=players.php?pid=387&edition=5>LUKABO-</a></td>
        <td>26</td>
        <td>6624.853</td>
        <td>264.000</td>
    </tr>
    <tr>
        <td>177</td>
        <td><a href=players.php?pid=28058&edition=5><span style='color:#0000ff;'>S</span><span
                    style='color:#0022ff;'>l</span><span style='color:#0033ff;'>i</span><span
                    style='color:#0055ff;'>n</span><span style='color:#0066ff;'>k</span><span
                    style='color:#0066ff;'>i</span><span style='color:#0088ff;'>i</span><span
                    style='color:#00aaff;'>i</span><span style='color:#00ccff;'>_</span></a></td>
        <td>26</td>
        <td>6625.200</td>
        <td>265.000</td>
    </tr>
    <tr>
        <td>178</td>
        <td><a href=players.php?pid=62929&edition=5>Marius.TM</a></td>
        <td>26</td>
        <td>6626.280</td>
        <td>268.115</td>
    </tr>
    <tr>
        <td>179</td>
        <td><a href=players.php?pid=66690&edition=5>blonsey</a></td>
        <td>26</td>
        <td>6627.640</td>
        <td>272.038</td>
    </tr>
    <tr>
        <td>180</td>
        <td><a href=players.php?pid=6976&edition=5><span style='color:#33aa55;'>Xe</span><span
                    style='color:#ffffff;'>ry</span></a></td>
        <td>25</td>
        <td>6711.493</td>
        <td>134.480</td>
    </tr>
    <tr>
        <td>181</td>
        <td><a href=players.php?pid=31102&edition=5><span style='color:#000000;'>eLx:smirkcat:</span></a></td>
        <td>25</td>
        <td>6714.640</td>
        <td>143.920</td>
    </tr>
    <tr>
        <td>182</td>
        <td><a href=players.php?pid=7463&edition=5>nejcig</a></td>
        <td>25</td>
        <td>6722.427</td>
        <td>167.280</td>
    </tr>
    <tr>
        <td>183</td>
        <td><a href=players.php?pid=54814&edition=5><span style='color:#1199ff;'>[</span><span
                    style='color:#11aaff;'>B</span><span style='color:#11bbff;'>o</span><span
                    style='color:#11ccff;'>b</span><span style='color:#00ddff;'>e</span><span
                    style='color:#00eeff;'>r</span><span style='color:#00ffff;'>]&nbsp;</span><span
                    style='color:#ff0000;'>FrankTheHamster</span></a></td>
        <td>25</td>
        <td>6728.427</td>
        <td>185.280</td>
    </tr>
    <tr>
        <td>184</td>
        <td><a href=players.php?pid=2369&edition=5>SvelT_TM</a></td>
        <td>25</td>
        <td>6745.000</td>
        <td>235.000</td>
    </tr>
    <tr>
        <td>185</td>
        <td><a href=players.php?pid=3188&edition=5><span style='color:#ff0000;'>Stew</span><span
                    style='color:#ffffff;'>ie</span></a></td>
        <td>25</td>
        <td>6746.627</td>
        <td>239.880</td>
    </tr>
    <tr>
        <td>186</td>
        <td><a href=players.php?pid=32457&edition=5>Butterfinger.37</a></td>
        <td>25</td>
        <td>6751.693</td>
        <td>255.080</td>
    </tr>
    <tr>
        <td>187</td>
        <td><a href=players.php?pid=33726&edition=5><span style='color:#00ccff;'>L</span><span
                    style='color:#44ddbb;'>e</span><span style='color:#88ee88;'>y</span><span
                    style='color:#bbee44;'>s</span><span style='color:#ffff00;'>i</span></a></td>
        <td>25</td>
        <td>6753.293</td>
        <td>259.880</td>
    </tr>
    <tr>
        <td>188</td>
        <td><a href=players.php?pid=1585&edition=5>:spmW:</a></td>
        <td>25</td>
        <td>6755.507</td>
        <td>266.520</td>
    </tr>
    <tr>
        <td>189</td>
        <td><a href=players.php?pid=31647&edition=5><span style='color:#6600ff;font-weight:bold;'>Đ</span><span
                    style='color:#8800ff;font-weight:bold;'>&lambda;</span><span
                    style='color:#9900ff;font-weight:bold;'>Қ</span><span
                    style='color:#9900ff;font-weight:bold;'>Ħ</span><span
                    style='color:#cc00ff;font-weight:bold;'>Ѧ</span><span
                    style='color:#ff00ff;font-weight:bold;'>Ѧ</span></a></td>
        <td>25</td>
        <td>6761.213</td>
        <td>283.640</td>
    </tr>
    <tr>
        <td>190</td>
        <td><a href=players.php?pid=42581&edition=5>Laurenff</a></td>
        <td>25</td>
        <td>6763.120</td>
        <td>289.360</td>
    </tr>
    <tr>
        <td>191</td>
        <td><a href=players.php?pid=6627&edition=5><span style='color:#663399;'>乌</span><span
                    style='color:#553399;'>ќ</span><span style='color:#443399;'>&otilde;</span><span
                    style='color:#333399;'>Ł</span><span style='color:#333399;'>Ľ</span><span
                    style='color:#886655;'>į</span><span style='color:#cc9900;'>į</span></a></td>
        <td>25</td>
        <td>6763.307</td>
        <td>289.920</td>
    </tr>
    <tr>
        <td>192</td>
        <td><a href=players.php?pid=7379&edition=5><span style='color:#ff00cc;font-weight:bold;'>H</span><span
                    style='color:#dd11bb;font-weight:bold;'>E</span><span
                    style='color:#bb22aa;font-weight:bold;'>G</span><span
                    style='color:#993399;font-weight:bold;'>E</span></a></td>
        <td>25</td>
        <td>6763.400</td>
        <td>290.200</td>
    </tr>
    <tr>
        <td>193</td>
        <td><a href=players.php?pid=48454&edition=5>Pdrz</a></td>
        <td>25</td>
        <td>6763.973</td>
        <td>291.920</td>
    </tr>
    <tr>
        <td>194</td>
        <td><a href=players.php?pid=7743&edition=5><span style='color:#ffee00;font-weight:bold;'>I</span><span
                    style='color:#ffffff;font-weight:bold;'>ntellectrick&nbsp;</span><span
                    style='color:#ffee00;font-weight:bold;'></span></a></td>
        <td>25</td>
        <td>6765.200</td>
        <td>295.600</td>
    </tr>
    <tr>
        <td>195</td>
        <td><a href=players.php?pid=17089&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;BaToL</span></a></td>
        <td>25</td>
        <td>6766.160</td>
        <td>298.480</td>
    </tr>
    <tr>
        <td>196</td>
        <td><a href=players.php?pid=12077&edition=5><span style='color:#ff9900;'>Noob</span><span
                    style='color:#ffffff;'>bcp</span></a></td>
        <td>25</td>
        <td>6768.053</td>
        <td>304.160</td>
    </tr>
    <tr>
        <td>197</td>
        <td><a href=players.php?pid=16055&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;Kryon</span></a></td>
        <td>25</td>
        <td>6774.387</td>
        <td>323.160</td>
    </tr>
    <tr>
        <td>198</td>
        <td><a href=players.php?pid=9499&edition=5>tim9367</a></td>
        <td>25</td>
        <td>6776.160</td>
        <td>328.480</td>
    </tr>
    <tr>
        <td>199</td>
        <td><a href=players.php?pid=48854&edition=5><span
                    style='color:#00ffff;font-style:italic;font-weight:bold;'>Staticiser</span></a></td>
        <td>25</td>
        <td>6781.800</td>
        <td>345.400</td>
    </tr>
    <tr>
        <td>200</td>
        <td><a href=players.php?pid=69154&edition=5>jarcklord.</a></td>
        <td>25</td>
        <td>6785.120</td>
        <td>355.360</td>
    </tr>
    <tr>
        <td>201</td>
        <td><a href=players.php?pid=29403&edition=5>Sengria</a></td>
        <td>25</td>
        <td>6787.987</td>
        <td>363.960</td>
    </tr>
    <tr>
        <td>202</td>
        <td><a href=players.php?pid=53191&edition=5><span style='color:#0033cc;'>T</span><span
                    style='color:#002266;'>r</span><span style='color:#000000;'>a</span><span
                    style='color:#000000;'>m</span><span style='color:#888888;'>1</span><span
                    style='color:#ffffff;'>5</span></a></td>
        <td>24</td>
        <td>6853.200</td>
        <td>166.250</td>
    </tr>
    <tr>
        <td>203</td>
        <td><a href=players.php?pid=7773&edition=5><span style='color:#0000ff;'>Nor</span><span
                    style='color:#ffffff;'>Tax</span></a></td>
        <td>24</td>
        <td>6876.467</td>
        <td>238.958</td>
    </tr>
    <tr>
        <td>204</td>
        <td><a href=players.php?pid=10385&edition=5><span style='color:#33aa55;'>Ric</span><span
                    style='color:#ffffff;'>ardino</span></a></td>
        <td>24</td>
        <td>6877.987</td>
        <td>243.708</td>
    </tr>
    <tr>
        <td>205</td>
        <td><a href=players.php?pid=2011&edition=5>acer</a></td>
        <td>24</td>
        <td>6878.160</td>
        <td>244.250</td>
    </tr>
    <tr>
        <td>206</td>
        <td><a href=players.php?pid=7840&edition=5><span style='color:#ffff00;'>Maechtiger</span><span
                    style='color:#00ff00;'>Mux</span></a></td>
        <td>24</td>
        <td>6880.200</td>
        <td>250.625</td>
    </tr>
    <tr>
        <td>207</td>
        <td><a href=players.php?pid=10272&edition=5><span
                    style='color:#00ccff;letter-spacing: -0.1em;font-size:smaller'>hankyyyyyy</span></a></td>
        <td>24</td>
        <td>6884.533</td>
        <td>264.167</td>
    </tr>
    <tr>
        <td>208</td>
        <td><a href=players.php?pid=1151&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>Brand0M</span></a></td>
        <td>24</td>
        <td>6886.160</td>
        <td>269.250</td>
    </tr>
    <tr>
        <td>209</td>
        <td><a href=players.php?pid=1043&edition=5><span style='color:#33aa55;'>Schmo</span><span
                    style='color:#ffffff;'>bias</span></a></td>
        <td>24</td>
        <td>6892.813</td>
        <td>290.042</td>
    </tr>
    <tr>
        <td>210</td>
        <td><a href=players.php?pid=29&edition=5><span style='color:#ff0000;font-style:italic;'>S</span><span
                    style='color:#cc1122;font-style:italic;'>i</span><span
                    style='color:#aa2244;font-style:italic;'>m</span><span
                    style='color:#772266;font-style:italic;'>p</span><span
                    style='color:#443388;font-style:italic;'>l</span><span
                    style='color:#443388;font-style:italic;'>y</span><span
                    style='color:#772266;font-style:italic;'>N</span><span
                    style='color:#aa2244;font-style:italic;'>i</span><span
                    style='color:#cc1122;font-style:italic;'>c</span><span
                    style='color:#ff0000;font-style:italic;'>k</span></a></td>
        <td>24</td>
        <td>6900.227</td>
        <td>313.208</td>
    </tr>
    <tr>
        <td>211</td>
        <td><a href=players.php?pid=64437&edition=5><span
                    style='color:#7788ff;font-weight:bold;'>Somber&nbsp;Fire</span></a></td>
        <td>24</td>
        <td>6900.240</td>
        <td>313.250</td>
    </tr>
    <tr>
        <td>212</td>
        <td><a href=players.php?pid=26&edition=5>karlberg&nbsp;<span style='color:#ffcc22;'>:</span><span
                    style='color:#ff9933;'>s</span><span style='color:#ee6633;'>m</span><span
                    style='color:#ee6633;'>i</span><span style='color:#ee5533;'>r</span><span
                    style='color:#ee3333;'>k</span><span style='color:#cc1177;'>c</span><span
                    style='color:#992277;'>a</span><span style='color:#662266;'>t</span><span
                    style='color:#333366;'>:&nbsp;</span></a></td>
        <td>24</td>
        <td>6918.360</td>
        <td>369.875</td>
    </tr>
    <tr>
        <td>213</td>
        <td><a href=players.php?pid=11415&edition=5><span style='color:#0000cc;'>Ł</span><span
                    style='color:#0011dd;'>&sigma;</span><span style='color:#0022dd;'>&alpha;</span><span
                    style='color:#0033ee;'>ȡ</span><span style='color:#0044ee;'>ϊ</span><span
                    style='color:#0055ff;'>ก</span><span style='color:#0066ff;'>ǥ&nbsp;</span><span
                    style='color:#66ffff;'>々&nbsp;</span><span style='color:#000000;'>&not;&nbsp;</span><span
                    style='color:#9900dd;font-style:italic;'>D</span><span
                    style='color:#9911dd;font-style:italic;'>a</span><span
                    style='color:#9933dd;font-style:italic;'>r</span><span
                    style='color:#9944dd;font-style:italic;'>k</span><span
                    style='color:#9966dd;font-style:italic;'>6</span><span
                    style='color:#9977dd;font-style:italic;'>2</span></a></td>
        <td>23</td>
        <td>7004.627</td>
        <td>232.478</td>
    </tr>
    <tr>
        <td>214</td>
        <td><a href=players.php?pid=13233&edition=5><span style='color:#44eeee;'>E</span><span
                    style='color:#ffccdd;'>lvzz</span></a></td>
        <td>23</td>
        <td>7012.587</td>
        <td>258.435</td>
    </tr>
    <tr>
        <td>215</td>
        <td><a href=players.php?pid=21590&edition=5><span style='color:#ff9900;'>Cla</span><span
                    style='color:#ffffff;'>spp&nbsp;:owo:</span></a></td>
        <td>23</td>
        <td>7014.427</td>
        <td>264.435</td>
    </tr>
    <tr>
        <td>216</td>
        <td><a href=players.php?pid=14468&edition=5><span style='color:#0000ff;'>F</span><span
                    style='color:#ffffff;'>i</span><span style='color:#000000;'>g</span><span
                    style='color:#0000ff;'>o</span><span style='color:#ffffff;'>_</span><span
                    style='color:#0000ff;'>H</span><span style='color:#ffffff;'>S</span><span
                    style='color:#000000;'>V</span></a></td>
        <td>23</td>
        <td>7015.067</td>
        <td>266.522</td>
    </tr>
    <tr>
        <td>217</td>
        <td><a href=players.php?pid=8222&edition=5><span style='color:#00ff00;font-style:italic;'>T</span><span
                    style='color:#88ff00;font-style:italic;'>a</span><span
                    style='color:#ffff00;font-style:italic;'>y</span><span
                    style='color:#ffff00;font-style:italic;'>.</span><span
                    style='color:#ff8800;font-style:italic;'>C</span><span
                    style='color:#ff0000;font-style:italic;'>o</span></a></td>
        <td>23</td>
        <td>7018.213</td>
        <td>276.783</td>
    </tr>
    <tr>
        <td>218</td>
        <td><a href=players.php?pid=11688&edition=5>:Prayge:&nbsp;<span
                    style='color:#9977dd;font-weight:bold;'>Đ</span><span
                    style='color:#aa66dd;font-weight:bold;'>Ŕ</span><span
                    style='color:#bb55dd;font-weight:bold;'>ā</span><span
                    style='color:#bb55dd;font-weight:bold;'>Ғ</span><span
                    style='color:#aa33dd;font-weight:bold;'>&tau;</span><span
                    style='color:#9900dd;font-weight:bold;'>Ί</span></a></td>
        <td>23</td>
        <td>7020.333</td>
        <td>283.696</td>
    </tr>
    <tr>
        <td>219</td>
        <td><a href=players.php?pid=23219&edition=5><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>ba</span><span
                    style='color:#330099;letter-spacing: -0.1em;font-size:smaller'>zrz</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>okh&nbsp;ᄓ&nbsp;</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>b</span><span
                    style='color:#330099;letter-spacing: -0.1em;font-size:smaller'>oo</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>st</span></a></td>
        <td>23</td>
        <td>7024.027</td>
        <td>295.739</td>
    </tr>
    <tr>
        <td>220</td>
        <td><a href=players.php?pid=57897&edition=5>Dagos</a></td>
        <td>23</td>
        <td>7027.453</td>
        <td>306.913</td>
    </tr>
    <tr>
        <td>221</td>
        <td><a href=players.php?pid=1091&edition=5><span style='color:#0000ff;'>Ly</span><span
                    style='color:#ffffff;'>k</span><span style='color:#ff0000;'>er</span><span
                    style='color:#000000;'>ヅ&nbsp;</span></a></td>
        <td>23</td>
        <td>7032.427</td>
        <td>323.130</td>
    </tr>
    <tr>
        <td>222</td>
        <td><a href=players.php?pid=32859&edition=5><span
                    style='color:#00ff00;font-style:italic;font-weight:bold;'>C</span><span
                    style='color:#00ee00;font-style:italic;font-weight:bold;'>l</span><span
                    style='color:#00dd00;font-style:italic;font-weight:bold;'>&clubs;</span><span
                    style='color:#00bb00;font-style:italic;font-weight:bold;'>v</span><span
                    style='color:#00aa00;font-style:italic;font-weight:bold;'>e</span><span
                    style='color:#009900;font-style:italic;font-weight:bold;'>r</span></a></td>
        <td>23</td>
        <td>7032.760</td>
        <td>324.217</td>
    </tr>
    <tr>
        <td>223</td>
        <td><a href=players.php?pid=29168&edition=5><span style='color:#00ffff;'>M</span><span
                    style='color:#55ffff;'>a</span><span style='color:#aaffff;'>r</span><span
                    style='color:#ffffff;'>t</span><span style='color:#ffffff;'>y</span>0<span
                    style='color:#55ffff;'>9</span><span style='color:#00ffff;'>3</span></a></td>
        <td>23</td>
        <td>7033.707</td>
        <td>327.304</td>
    </tr>
    <tr>
        <td>224</td>
        <td><a href=players.php?pid=51687&edition=5>IdrissLArtiste</a></td>
        <td>23</td>
        <td>7037.693</td>
        <td>340.304</td>
    </tr>
    <tr>
        <td>225</td>
        <td><a href=players.php?pid=7415&edition=5><span style='color:#6600ff;'>M</span><span
                    style='color:#6622ff;'>a</span><span style='color:#6644ff;'>j</span><span
                    style='color:#6666ff;'>i</span></a></td>
        <td>23</td>
        <td>7054.333</td>
        <td>394.565</td>
    </tr>
    <tr>
        <td>226</td>
        <td><a href=players.php?pid=61186&edition=5><span style='color:#0000cc;'>Ł</span><span
                    style='color:#0011dd;'>&sigma;</span><span style='color:#0022dd;'>&alpha;</span><span
                    style='color:#0033ee;'>ȡ</span><span style='color:#0044ee;'>ϊ</span><span
                    style='color:#0055ff;'>ก</span><span style='color:#0066ff;'>ǥ&nbsp;</span><span
                    style='color:#66ffff;'>々&nbsp;</span><span style='color:#000000;'>&not;&nbsp;</span><span
                    style='color:#ffff00;'>&Lambda;</span><span style='color:#ffdd00;'>&upsilon;</span><span
                    style='color:#ffbb00;'>w</span><span style='color:#ff9900;'>г</span><span
                    style='color:#ff9900;'>&alpha;</span><span style='color:#ff6600;'>h</span><span
                    style='color:#ff3300;'>&nbsp;</span><span style='color:#ff0000;'>ϟ</span></a></td>
        <td>22</td>
        <td>7130.307</td>
        <td>216.955</td>
    </tr>
    <tr>
        <td>227</td>
        <td><a href=players.php?pid=19455&edition=5>Ricso5</a></td>
        <td>22</td>
        <td>7133.253</td>
        <td>227.000</td>
    </tr>
    <tr>
        <td>228</td>
        <td><a href=players.php?pid=29843&edition=5><span style='color:#0000ff;'>Norsu</span><span
                    style='color:#ff00ff;'>TM</span></a></td>
        <td>22</td>
        <td>7139.187</td>
        <td>247.227</td>
    </tr>
    <tr>
        <td>229</td>
        <td><a href=players.php?pid=6585&edition=5>TW&nbsp;<span style='color:#ff0000;'>Y</span><span
                    style='color:#ffffff;'>n&oslash;s</span></a></td>
        <td>22</td>
        <td>7140.280</td>
        <td>250.955</td>
    </tr>
    <tr>
        <td>230</td>
        <td><a href=players.php?pid=13983&edition=5>Tannuleet</a></td>
        <td>22</td>
        <td>7141.627</td>
        <td>255.545</td>
    </tr>
    <tr>
        <td>231</td>
        <td><a href=players.php?pid=38276&edition=5>Stelius&bull;&nbsp;</a></td>
        <td>22</td>
        <td>7145.067</td>
        <td>267.273</td>
    </tr>
    <tr>
        <td>232</td>
        <td><a href=players.php?pid=50247&edition=5><span style='color:#006677;'>L</span><span
                    style='color:#118888;'>e</span><span style='color:#339999;'>G</span><span
                    style='color:#44aaaa;'>a</span><span style='color:#55bbbb;'>b</span><span
                    style='color:#77cccc;'>2</span><span style='color:#88eedd;'>8</span></a></td>
        <td>22</td>
        <td>7146.813</td>
        <td>273.227</td>
    </tr>
    <tr>
        <td>233</td>
        <td><a href=players.php?pid=61959&edition=5>310&nbsp;save&nbsp;me</a></td>
        <td>22</td>
        <td>7147.613</td>
        <td>275.955</td>
    </tr>
    <tr>
        <td>234</td>
        <td><a href=players.php?pid=67718&edition=5>GranaDy.</a></td>
        <td>22</td>
        <td>7150.640</td>
        <td>286.273</td>
    </tr>
    <tr>
        <td>235</td>
        <td><a href=players.php?pid=46373&edition=5><span style='color:#006699;'>E</span><span
                    style='color:#007788;'>lu</span><span style='color:#008877;'>si</span><span
                    style='color:#009966;'>v</span><span style='color:#009966;'>e</span><span
                    style='color:#00bb66;'>r</span><span style='color:#00cc66;'>i</span><span
                    style='color:#00ee66;'>o</span><span style='color:#00ff66;'>s</span></a></td>
        <td>22</td>
        <td>7156.133</td>
        <td>305.000</td>
    </tr>
    <tr>
        <td>236</td>
        <td><a href=players.php?pid=14217&edition=5>Hockeyfan48</a></td>
        <td>22</td>
        <td>7156.453</td>
        <td>306.091</td>
    </tr>
    <tr>
        <td>237</td>
        <td><a href=players.php?pid=12412&edition=5><span style='color:#000000;'>D</span><span
                    style='color:#dd0000;'>e</span><span style='color:#ddff00;'>r</span><span
                    style='color:#ddffbb;'>〢</span><span style='color:#33ff33;'>Schuldenberater</span></a></td>
        <td>22</td>
        <td>7158.360</td>
        <td>312.591</td>
    </tr>
    <tr>
        <td>238</td>
        <td><a href=players.php?pid=6478&edition=5><span style='color:#ddaa22;'>S</span><span
                    style='color:#ffffff;'>ค&eta;ԃҽץ.</span><span style='color:#ddaa22;'>тм</span></a></td>
        <td>22</td>
        <td>7158.920</td>
        <td>314.500</td>
    </tr>
    <tr>
        <td>239</td>
        <td><a href=players.php?pid=64101&edition=5>Glimse5678</a></td>
        <td>22</td>
        <td>7160.000</td>
        <td>318.182</td>
    </tr>
    <tr>
        <td>240</td>
        <td><a href=players.php?pid=52483&edition=5><span style='color:#44eedd;'>A</span><span
                    style='color:#339999;'>ฝ</span><span style='color:#115544;'>Ҟ</span><span
                    style='color:#000000;'>ฝ</span><span style='color:#000000;'>Ą</span><span
                    style='color:#883322;'>R</span><span style='color:#ff6644;'>Đ</span></a></td>
        <td>22</td>
        <td>7163.213</td>
        <td>329.136</td>
    </tr>
    <tr>
        <td>241</td>
        <td><a href=players.php?pid=52968&edition=5><span style='color:#00ffff;'>N</span><span
                    style='color:#00ddff;'>e</span><span style='color:#11bbff;'>v</span><span
                    style='color:#1199ff;'>e</span><span style='color:#1199ff;'>n</span><span
                    style='color:#4466ff;'>R</span><span style='color:#6633ff;'>G</span></a></td>
        <td>22</td>
        <td>7170.133</td>
        <td>352.727</td>
    </tr>
    <tr>
        <td>242</td>
        <td><a href=players.php?pid=45522&edition=5><span style='color:#ff0000;'>〶</span><span
                    style='color:#ff3300;'>i</span><span style='color:#ff6600;'>e</span><span
                    style='color:#ff9900;'>z</span><span style='color:#ffcc00;'>i</span><span
                    style='color:#ffff00;'>e</span></a></td>
        <td>22</td>
        <td>7177.640</td>
        <td>378.318</td>
    </tr>
    <tr>
        <td>243</td>
        <td><a href=players.php?pid=179&edition=5>Aquariummm</a></td>
        <td>22</td>
        <td>7179.093</td>
        <td>383.273</td>
    </tr>
    <tr>
        <td>244</td>
        <td><a href=players.php?pid=51757&edition=5><span style='color:#00ccff;'>Ts</span><span
                    style='color:#ff00ff;'>UwU</span><span style='color:#00ccff;'>namX</span></a></td>
        <td>22</td>
        <td>7180.600</td>
        <td>388.409</td>
    </tr>
    <tr>
        <td>245</td>
        <td><a href=players.php?pid=41118&edition=5><span style='color:#00eeff;'>C</span><span
                    style='color:#66ccff;'>r</span><span style='color:#88aaff;'>a</span><span
                    style='color:#9988ff;'>b</span><span style='color:#eeee00;'></span><span
                    style='color:#aa00ff;'>n</span></a></td>
        <td>21</td>
        <td>7254.587</td>
        <td>194.952</td>
    </tr>
    <tr>
        <td>246</td>
        <td><a href=players.php?pid=11876&edition=5><span style='color:#ff0000;'>Leg</span><span
                    style='color:#880088;'>io</span><span style='color:#5544aa;'>n</span><span
                    style='color:#3377dd;'>2k&nbsp;</span><span style='color:#ff0000;'></span></a></td>
        <td>21</td>
        <td>7266.640</td>
        <td>238.000</td>
    </tr>
    <tr>
        <td>247</td>
        <td><a href=players.php?pid=38379&edition=5><span style='color:#33aa55;font-weight:bold;'>Tom</span><span
                    style='color:#ffffff;font-weight:bold;'>mopolis</span></a></td>
        <td>21</td>
        <td>7266.907</td>
        <td>238.952</td>
    </tr>
    <tr>
        <td>248</td>
        <td><a href=players.php?pid=33495&edition=5><span style='color:#990099;'>M</span><span
                    style='color:#8822aa;'>o</span><span style='color:#6633bb;'>u</span><span
                    style='color:#5555cc;'>n</span><span style='color:#3366dd;'>t</span><span
                    style='color:#2288ee;'>a</span><span style='color:#0099ff;'>i</span><span
                    style='color:#0099ff;'>n</span><span style='color:#0099dd;'>D</span><span
                    style='color:#0099aa;'>i</span><span style='color:#009988;'>e</span><span
                    style='color:#009955;'>s</span><span style='color:#009933;'>e</span><span
                    style='color:#009900;'>l</span></a></td>
        <td>21</td>
        <td>7268.893</td>
        <td>246.048</td>
    </tr>
    <tr>
        <td>249</td>
        <td><a href=players.php?pid=66039&edition=5>MultiTrigger</a></td>
        <td>21</td>
        <td>7276.387</td>
        <td>272.810</td>
    </tr>
    <tr>
        <td>250</td>
        <td><a href=players.php?pid=35692&edition=5>DarrahTM</a></td>
        <td>21</td>
        <td>7279.413</td>
        <td>283.619</td>
    </tr>
    <tr>
        <td>251</td>
        <td><a href=players.php?pid=28094&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;LeGrandDadet</span></a></td>
        <td>21</td>
        <td>7284.187</td>
        <td>300.667</td>
    </tr>
    <tr>
        <td>252</td>
        <td><a href=players.php?pid=29729&edition=5><span style='color:#000000;'>r</span><span
                    style='color:#000000;'>y</span><span style='color:#000000;'>u</span><span
                    style='color:#ff0000;'>k</span><span style='color:#000000;'>冬</span></a></td>
        <td>21</td>
        <td>7289.560</td>
        <td>319.857</td>
    </tr>
    <tr>
        <td>253</td>
        <td><a href=players.php?pid=35169&edition=5><span style='color:#dddd11;'>KaasHaas:cheese:</span></a></td>
        <td>21</td>
        <td>7291.547</td>
        <td>326.952</td>
    </tr>
    <tr>
        <td>254</td>
        <td><a href=players.php?pid=52010&edition=5>Joyboy</a></td>
        <td>21</td>
        <td>7294.187</td>
        <td>336.381</td>
    </tr>
    <tr>
        <td>255</td>
        <td><a href=players.php?pid=6876&edition=5><span style='color:#000000;font-weight:bold;'>I</span><span
                    style='font-weight:bold;'>uli</span><span style='color:#ffbb00;font-weight:bold;'>c</span><span
                    style='font-weight:bold;'>iou</span><span style='color:#ff0000;font-weight:bold;'>s</span></a></td>
        <td>21</td>
        <td>7302.347</td>
        <td>365.524</td>
    </tr>
    <tr>
        <td>256</td>
        <td><a href=players.php?pid=51728&edition=5>Petvaria.</a></td>
        <td>21</td>
        <td>7304.720</td>
        <td>374.000</td>
    </tr>
    <tr>
        <td>257</td>
        <td><a href=players.php?pid=6558&edition=5><span style='color:#ffffff;'>Brau</span><span
                    style='color:#ff0000;'>sen</span></a></td>
        <td>21</td>
        <td>7310.920</td>
        <td>396.143</td>
    </tr>
    <tr>
        <td>258</td>
        <td><a href=players.php?pid=66882&edition=5>fruixy</a></td>
        <td>21</td>
        <td>7321.013</td>
        <td>432.190</td>
    </tr>
    <tr>
        <td>259</td>
        <td><a href=players.php?pid=33935&edition=5><span style='color:#33ff00;'>RezRect</span></a></td>
        <td>21</td>
        <td>7327.147</td>
        <td>454.095</td>
    </tr>
    <tr>
        <td>260</td>
        <td><a href=players.php?pid=6182&edition=5><span style='color:#990099;'>&middot;</span><span
                    style='color:#ff00ff;'>͵</span><span style='color:#ff0000;'>े</span><span
                    style='color:#ffffff;'>wikos</span><span style='color:#00ff00;'>'</span><span
                    style='color:#5599ff;'>्</span><span style='color:#ffff00;'>॔</span><span
                    style='color:#0055ff;'>.</span><span style='color:#00aa00;'>`</span></a></td>
        <td>20</td>
        <td>7403.600</td>
        <td>263.500</td>
    </tr>
    <tr>
        <td>261</td>
        <td><a href=players.php?pid=66156&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;Possessium</span></a></td>
        <td>20</td>
        <td>7406.933</td>
        <td>276.000</td>
    </tr>
    <tr>
        <td>262</td>
        <td><a href=players.php?pid=20&edition=5>HelionTM</a></td>
        <td>20</td>
        <td>7407.360</td>
        <td>277.600</td>
    </tr>
    <tr>
        <td>263</td>
        <td><a href=players.php?pid=6618&edition=5>Korniee</a></td>
        <td>20</td>
        <td>7407.907</td>
        <td>279.650</td>
    </tr>
    <tr>
        <td>264</td>
        <td><a href=players.php?pid=8768&edition=5><span style='color:#55ff99;font-style:italic;'>J</span><span
                    style='color:#55ff66;font-style:italic;'>e</span><span
                    style='color:#55ff33;font-style:italic;'>t</span><span
                    style='color:#55ff11;font-style:italic;'>.</span></a></td>
        <td>20</td>
        <td>7409.533</td>
        <td>285.750</td>
    </tr>
    <tr>
        <td>265</td>
        <td><a href=players.php?pid=7054&edition=5>tuduttuduu</a></td>
        <td>20</td>
        <td>7413.920</td>
        <td>302.200</td>
    </tr>
    <tr>
        <td>266</td>
        <td><a href=players.php?pid=35389&edition=5><span style='color:#000000;'>尺</span><span
                    style='color:#330000;'>&oslash;</span><span style='color:#660000;'>ｬ</span><span
                    style='color:#990000;'>ҝ</span><span style='color:#cc0000;'>&epsilon;</span><span
                    style='color:#ff0000;'>.</span></a></td>
        <td>20</td>
        <td>7414.973</td>
        <td>306.150</td>
    </tr>
    <tr>
        <td>267</td>
        <td><a href=players.php?pid=17943&edition=5><span style='color:#11bb77;font-style:italic;'>Բabsterrr</span></a>
        </td>
        <td>20</td>
        <td>7419.053</td>
        <td>321.450</td>
    </tr>
    <tr>
        <td>268</td>
        <td><a href=players.php?pid=7395&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='color:#0099cc;font-style:italic;'>Denniss</span></a></td>
        <td>20</td>
        <td>7421.707</td>
        <td>331.400</td>
    </tr>
    <tr>
        <td>269</td>
        <td><a href=players.php?pid=10892&edition=5><span style='color:#000066;'>S</span><span
                    style='color:#000088;'>h</span><span style='color:#0000aa;'>a</span><span
                    style='color:#0000cc;'>d</span><span style='color:#0000cc;'>o</span><span
                    style='color:#0066ee;'>w</span><span style='color:#00bbff;'>开</span></a></td>
        <td>20</td>
        <td>7422.267</td>
        <td>333.500</td>
    </tr>
    <tr>
        <td>270</td>
        <td><a href=players.php?pid=66191&edition=5><span style='color:#1177ff;'>D</span><span
                    style='color:#1188ff;'>a</span><span style='color:#11aaff;'>i</span><span
                    style='color:#11bbff;'>k</span><span style='color:#11ddff;'>y</span><span
                    style='color:#00eeff;'>i</span></a></td>
        <td>20</td>
        <td>7424.147</td>
        <td>340.550</td>
    </tr>
    <tr>
        <td>271</td>
        <td><a href=players.php?pid=49948&edition=5><span style='color:#003399;'>N</span><span
                    style='color:#005599;'>o</span><span style='color:#006699;'>v</span><span
                    style='color:#008899;'>a</span><span style='color:#009999;'>C</span><span
                    style='color:#009999;'>h</span><span style='color:#008877;'>r</span><span
                    style='color:#007755;'>1</span><span style='color:#006633;'>3</span></a></td>
        <td>20</td>
        <td>7425.200</td>
        <td>344.500</td>
    </tr>
    <tr>
        <td>272</td>
        <td><a href=players.php?pid=3222&edition=5>J4nur</a></td>
        <td>20</td>
        <td>7427.987</td>
        <td>354.950</td>
    </tr>
    <tr>
        <td>273</td>
        <td><a href=players.php?pid=54011&edition=5><span style='color:#4400aa;'>Pu</span><span
                    style='color:#3311aa;'>rp</span><span style='color:#221199;'>le&nbsp;</span><span
                    style='color:#002288;'>Du</span><span style='color:#003388;'>o-</span><span
                    style='color:#4400aa;'>h</span><span style='color:#4411aa;'>i</span><span
                    style='color:#3322bb;'>j</span><span style='color:#2233bb;'>b</span><span
                    style='color:#2233cc;'>i</span><span style='color:#1144cc;'>r</span><span
                    style='color:#1155dd;'>d</span><span style='color:#6644aa;'></span></a></td>
        <td>20</td>
        <td>7429.667</td>
        <td>361.250</td>
    </tr>
    <tr>
        <td>274</td>
        <td><a href=players.php?pid=68327&edition=5><span style='color:#336699;'>Of</span><span
                    style='color:#ffccff;'>Machi</span><span style='color:#336699;'>nations</span></a></td>
        <td>20</td>
        <td>7440.413</td>
        <td>401.550</td>
    </tr>
    <tr>
        <td>275</td>
        <td><a href=players.php?pid=66304&edition=5><span
                    style='color:#66aaff;font-style:italic;font-weight:bold;'>S</span><span
                    style='color:#77aaff;font-style:italic;font-weight:bold;'>t</span><span
                    style='color:#8899ff;font-style:italic;font-weight:bold;'>e</span><span
                    style='color:#9988ff;font-style:italic;font-weight:bold;'>a</span><span
                    style='color:#bb77ff;font-style:italic;font-weight:bold;'>l</span><span
                    style='color:#cc77ff;font-style:italic;font-weight:bold;'>t</span><span
                    style='color:#dd66ee;font-style:italic;font-weight:bold;'>h</span><span
                    style='color:#ee55ee;font-style:italic;font-weight:bold;'>J</span><span
                    style='color:#ff44ee;font-style:italic;font-weight:bold;'>T</span></a></td>
        <td>20</td>
        <td>7465.040</td>
        <td>493.900</td>
    </tr>
    <tr>
        <td>276</td>
        <td><a href=players.php?pid=51740&edition=5><span style='color:#ff00ff;font-weight:bold;'>Y</span><span
                    style='color:#cc00ff;font-weight:bold;'>u</span><span
                    style='color:#9900ff;font-weight:bold;'>n</span><span
                    style='color:#6600ff;font-weight:bold;'>a</span><span
                    style='color:#3300ff;font-weight:bold;'>t</span><span
                    style='color:#0000ff;font-weight:bold;'>h</span></a></td>
        <td>19</td>
        <td>7526.893</td>
        <td>237.737</td>
    </tr>
    <tr>
        <td>277</td>
        <td><a href=players.php?pid=26787&edition=5><span style='color:#00ffff;'>Kryli..</span></a></td>
        <td>19</td>
        <td>7528.533</td>
        <td>244.211</td>
    </tr>
    <tr>
        <td>278</td>
        <td><a href=players.php?pid=63464&edition=5><span style='font-style:italic;'>&nbsp;</span><span
                    style='color:#ff0000;font-style:italic;'>&nbsp;npr&nbsp;:hmmnotes:</span></a></td>
        <td>19</td>
        <td>7530.467</td>
        <td>251.842</td>
    </tr>
    <tr>
        <td>279</td>
        <td><a href=players.php?pid=24225&edition=5>Hayiom..</a></td>
        <td>19</td>
        <td>7535.200</td>
        <td>270.526</td>
    </tr>
    <tr>
        <td>280</td>
        <td><a href=players.php?pid=397&edition=5>Jxliano</a></td>
        <td>19</td>
        <td>7552.160</td>
        <td>337.474</td>
    </tr>
    <tr>
        <td>281</td>
        <td><a href=players.php?pid=6455&edition=5><span style='color:#33ffff;'>Ѕ&rho;</span><span
                    style='color:#99ccff;'>&alpha;</span><span style='color:#ff99ff;'>&cent;є</span><span
                    style='color:#000000;'>_</span><span style='color:#ff99ff;'>Ŀ&alpha;</span><span
                    style='color:#99ccff;'>ט</span><span style='color:#33ffff;'>&cent;ん</span></a></td>
        <td>19</td>
        <td>7552.560</td>
        <td>339.053</td>
    </tr>
    <tr>
        <td>282</td>
        <td><a href=players.php?pid=64632&edition=5><span style='color:#000000;font-style:italic;'>augst22nd</span></a>
        </td>
        <td>19</td>
        <td>7553.267</td>
        <td>341.842</td>
    </tr>
    <tr>
        <td>283</td>
        <td><a href=players.php?pid=66165&edition=5><span
                    style='color:#228822;font-style:italic;font-weight:bold;'>h</span><span
                    style='color:#448844;font-style:italic;font-weight:bold;'>a</span><span
                    style='color:#668866;font-style:italic;font-weight:bold;'>z</span><span
                    style='color:#888888;font-style:italic;font-weight:bold;'>y</span><span
                    style='color:#888888;font-style:italic;font-weight:bold;'>&nbsp;:smirkcat:</span></a></td>
        <td>19</td>
        <td>7559.160</td>
        <td>365.105</td>
    </tr>
    <tr>
        <td>284</td>
        <td><a href=players.php?pid=51906&edition=5>MALLY.TM</a></td>
        <td>19</td>
        <td>7559.267</td>
        <td>365.526</td>
    </tr>
    <tr>
        <td>285</td>
        <td><a href=players.php?pid=52826&edition=5>A-SoronSR</a></td>
        <td>19</td>
        <td>7564.147</td>
        <td>384.789</td>
    </tr>
    <tr>
        <td>286</td>
        <td><a href=players.php?pid=21982&edition=5><span style='color:#dd2299;'>N</span><span
                    style='color:#cc44aa;'>i</span><span style='color:#bb66bb;'>k</span><span
                    style='color:#bb66bb;'>k</span><span style='color:#0000ff;'>u</span></a></td>
        <td>19</td>
        <td>7577.520</td>
        <td>437.579</td>
    </tr>
    <tr>
        <td>287</td>
        <td><a href=players.php?pid=53468&edition=5><span style='color:#9933cc;'>B</span><span
                    style='color:#aa22cc;'>r</span><span style='color:#bb22cc;'>a</span><span
                    style='color:#dd11cc;'>i</span><span style='color:#ee11cc;'>n</span><span
                    style='color:#ff00cc;'>y</span></a></td>
        <td>19</td>
        <td>7579.520</td>
        <td>445.474</td>
    </tr>
    <tr>
        <td>288</td>
        <td><a href=players.php?pid=22900&edition=5>Krabbish_</a></td>
        <td>19</td>
        <td>7579.773</td>
        <td>446.474</td>
    </tr>
    <tr>
        <td>289</td>
        <td><a href=players.php?pid=22421&edition=5>:owo:<span style='color:#cc3333;font-weight:bold;'>S</span><span
                    style='color:#cc3366;font-weight:bold;'>h</span><span
                    style='color:#cc3399;font-weight:bold;'>e</span><span
                    style='color:#bb22cc;font-weight:bold;'>e</span><span
                    style='color:#bb22ff;font-weight:bold;'>p</span></a></td>
        <td>19</td>
        <td>7582.413</td>
        <td>456.895</td>
    </tr>
    <tr>
        <td>290</td>
        <td><a href=players.php?pid=9101&edition=5><span style='color:#00ccff;'>Ri</span><span
                    style='color:#0099ff;'>p</span><span style='color:#0066ff;'>p</span><span
                    style='color:#0033ff;'>in</span></a></td>
        <td>19</td>
        <td>7584.320</td>
        <td>464.421</td>
    </tr>
    <tr>
        <td>291</td>
        <td><a href=players.php?pid=31347&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Dracopho</span></a></td>
        <td>18</td>
        <td>7643.987</td>
        <td>183.278</td>
    </tr>
    <tr>
        <td>292</td>
        <td><a href=players.php?pid=33432&edition=5><span style='color:#0066ff;'>L</span><span
                    style='color:#3388cc;'>e</span><span style='color:#66aa99;'>o</span><span
                    style='color:#99bb66;'>n</span><span style='color:#ccdd33;'>e</span><span
                    style='color:#ffff00;'>s</span></a></td>
        <td>18</td>
        <td>7652.573</td>
        <td>219.056</td>
    </tr>
    <tr>
        <td>293</td>
        <td><a href=players.php?pid=852&edition=5><span style='color:#1188bb;'>B</span><span
                    style='color:#1177aa;'>4</span><span style='color:#116688;'>S</span><span
                    style='color:#115577;'>T</span><span style='color:#114466;'>1</span><span
                    style='color:#113344;'>.</span><span style='color:#002233;'>T</span><span
                    style='color:#001122;'>M&nbsp;:prayge:</span></a></td>
        <td>18</td>
        <td>7665.933</td>
        <td>274.722</td>
    </tr>
    <tr>
        <td>294</td>
        <td><a href=players.php?pid=52488&edition=5>[<span style='color:#ff0000;'>B</span><span
                    style='color:#ff5500;'>A</span><span style='color:#ffaa00;'>L</span><span
                    style='color:#ffff00;'>D</span>]&nbsp;Bald_tm</a></td>
        <td>18</td>
        <td>7672.587</td>
        <td>302.444</td>
    </tr>
    <tr>
        <td>295</td>
        <td><a href=players.php?pid=65239&edition=5>Osqri</a></td>
        <td>18</td>
        <td>7678.427</td>
        <td>326.778</td>
    </tr>
    <tr>
        <td>296</td>
        <td><a href=players.php?pid=6335&edition=5><span style='color:#9933ff;'>N</span><span
                    style='color:#aa22cc;'>a</span><span style='color:#bb2299;'>y</span><span
                    style='color:#dd1166;'>z</span><span style='color:#ee1133;'>T</span><span
                    style='color:#ff0000;'>M</span></a></td>
        <td>18</td>
        <td>7678.880</td>
        <td>328.667</td>
    </tr>
    <tr>
        <td>297</td>
        <td><a href=players.php?pid=29275&edition=5><span style='color:#0033cc;'>D</span><span
                    style='color:#0033ee;'>a</span><span style='color:#0033ff;'>n</span><span
                    style='color:#0033ff;'>d</span><span style='color:#0066ee;'>e</span><span
                    style='color:#0099cc;'>e</span></a></td>
        <td>18</td>
        <td>7679.973</td>
        <td>333.222</td>
    </tr>
    <tr>
        <td>298</td>
        <td><a href=players.php?pid=29557&edition=5><span style='color:#9900ff;font-weight:bold;'>PUG</span></a></td>
        <td>18</td>
        <td>7681.693</td>
        <td>340.389</td>
    </tr>
    <tr>
        <td>299</td>
        <td><a href=players.php?pid=52382&edition=5>CptMe0w</a></td>
        <td>18</td>
        <td>7687.200</td>
        <td>363.333</td>
    </tr>
    <tr>
        <td>300</td>
        <td><a href=players.php?pid=29126&edition=5><span
                    style='color:#990000;letter-spacing: -0.1em;font-size:smaller'>Ryuu</span>ganji</a></td>
        <td>18</td>
        <td>7687.640</td>
        <td>365.167</td>
    </tr>
    <tr>
        <td>301</td>
        <td><a href=players.php?pid=21611&edition=5><span style='color:#99ffff;font-weight:bold;'>Th</span><span
                    style='color:#66ffff;font-weight:bold;'>eN</span><span
                    style='color:#33cccc;font-weight:bold;'>4k</span><span
                    style='color:#339999;font-weight:bold;'>ed</span><span
                    style='color:#006666;font-weight:bold;'>As</span><span
                    style='color:#006699;font-weight:bold;'>ia</span><span
                    style='color:#003399;font-weight:bold;'>n</span></a></td>
        <td>18</td>
        <td>7689.173</td>
        <td>371.556</td>
    </tr>
    <tr>
        <td>302</td>
        <td><a href=players.php?pid=8005&edition=5><span style='color:#55ccff;'>T</span><span
                    style='color:#ffaabb;'>R</span><span style='color:#ffffff;'>A</span><span
                    style='color:#ffaabb;'>N</span><span style='color:#55ccff;'>S</span><span
                    style='color:#ffffff;'>grabou</span></a></td>
        <td>18</td>
        <td>7692.173</td>
        <td>384.056</td>
    </tr>
    <tr>
        <td>303</td>
        <td><a href=players.php?pid=66327&edition=5><span style='color:#008877;'>t</span><span
                    style='color:#22aa88;'>u</span><span style='color:#55bbaa;'>r</span><span
                    style='color:#77ddbb;'>b</span><span style='color:#99eecc;'>o</span><span
                    style='color:#ffffff;'>.</span><span style='color:#77aadd;'>b</span><span
                    style='color:#6677bb;'>e</span><span style='color:#555599;'>a</span><span
                    style='color:#442277;'>r</span></a></td>
        <td>18</td>
        <td>7693.373</td>
        <td>389.056</td>
    </tr>
    <tr>
        <td>304</td>
        <td><a href=players.php?pid=9445&edition=5>Eltev_X</a></td>
        <td>18</td>
        <td>7699.680</td>
        <td>415.333</td>
    </tr>
    <tr>
        <td>305</td>
        <td><a href=players.php?pid=52653&edition=5>beidlpracker22</a></td>
        <td>18</td>
        <td>7699.973</td>
        <td>416.556</td>
    </tr>
    <tr>
        <td>306</td>
        <td><a href=players.php?pid=41176&edition=5><span style='color:#ffee22;font-weight:bold;'>/</span><span
                    style='color:#ff9900;font-weight:bold;'>/</span><span
                    style='color:#001166;font-weight:bold;'>/&nbsp;</span><span style='color:#ffffff;'>TvSubZ</span></a>
        </td>
        <td>18</td>
        <td>7702.493</td>
        <td>427.056</td>
    </tr>
    <tr>
        <td>307</td>
        <td><a href=players.php?pid=6535&edition=5><span style='color:#33aa55;'>No</span><span
                    style='color:#ffffff;'>:mad:</span></a></td>
        <td>18</td>
        <td>7705.520</td>
        <td>439.667</td>
    </tr>
    <tr>
        <td>308</td>
        <td><a href=players.php?pid=8164&edition=5><span style='color:#0000ff;'>K</span><span
                    style='color:#5522ee;'>ę</span><span style='color:#9933cc;'>ŧ</span><span
                    style='color:#9933cc;'>ŝ</span><span style='color:#ff1199;'>บ</span></a></td>
        <td>18</td>
        <td>7707.093</td>
        <td>446.222</td>
    </tr>
    <tr>
        <td>309</td>
        <td><a href=players.php?pid=7673&edition=5><span style='color:#33aa55;'>s</span><span
                    style='color:#ffffff;'>e</span><span style='color:#33aa55;'>x</span><span
                    style='color:#ffffff;'>ske</span></a></td>
        <td>18</td>
        <td>7708.680</td>
        <td>452.833</td>
    </tr>
    <tr>
        <td>310</td>
        <td><a href=players.php?pid=47963&edition=5>_</a></td>
        <td>17</td>
        <td>7779.093</td>
        <td>201.882</td>
    </tr>
    <tr>
        <td>311</td>
        <td><a href=players.php?pid=66227&edition=5>Toppish146</a></td>
        <td>17</td>
        <td>7784.387</td>
        <td>225.235</td>
    </tr>
    <tr>
        <td>312</td>
        <td><a href=players.php?pid=10669&edition=5>Sushi-tm</a></td>
        <td>17</td>
        <td>7793.453</td>
        <td>265.235</td>
    </tr>
    <tr>
        <td>313</td>
        <td><a href=players.php?pid=32574&edition=5>TJ-TM</a></td>
        <td>17</td>
        <td>7794.893</td>
        <td>271.588</td>
    </tr>
    <tr>
        <td>314</td>
        <td><a href=players.php?pid=8708&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Silixior&nbsp;</span></a></td>
        <td>17</td>
        <td>7798.507</td>
        <td>287.529</td>
    </tr>
    <tr>
        <td>315</td>
        <td><a href=players.php?pid=7522&edition=5><span style='color:#ff9900;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff9900;'>T&nbsp;</span><span
                    style='color:#ffffff;'>I&nbsp;</span><span style='color:#ffffff;'>C</span><span
                    style='color:#ddffff;'>f</span><span style='color:#bbeeee;'>i</span><span
                    style='color:#99eeee;'>l</span><span style='color:#77dddd;'>7</span><span
                    style='color:#55dddd;'>7</span><span style='color:#33cccc;'>7</span></a></td>
        <td>17</td>
        <td>7798.547</td>
        <td>287.706</td>
    </tr>
    <tr>
        <td>316</td>
        <td><a href=players.php?pid=31590&edition=5>iBondKC</a></td>
        <td>17</td>
        <td>7799.067</td>
        <td>290.000</td>
    </tr>
    <tr>
        <td>317</td>
        <td><a href=players.php?pid=23176&edition=5>tv</a></td>
        <td>17</td>
        <td>7801.213</td>
        <td>299.471</td>
    </tr>
    <tr>
        <td>318</td>
        <td><a href=players.php?pid=30707&edition=5><span style='color:#990033;'>Ӄ</span><span
                    style='color:#bb5588;'>a</span><span style='color:#ddaadd;'>m</span><span
                    style='color:#ddaadd;'>m</span><span style='color:#ffccff;'>y</span></a></td>
        <td>17</td>
        <td>7811.213</td>
        <td>343.588</td>
    </tr>
    <tr>
        <td>319</td>
        <td><a href=players.php?pid=6699&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;A&nbsp;Nidalgo</span></a></td>
        <td>17</td>
        <td>7812.293</td>
        <td>348.353</td>
    </tr>
    <tr>
        <td>320</td>
        <td><a href=players.php?pid=32071&edition=5><span style='color:#44ddff;'>T</span><span
                    style='color:#55ccff;'>r</span><span style='color:#77ccff;'>i</span><span
                    style='color:#88bbff;'>c</span><span style='color:#99aaff;'>k</span><span
                    style='color:#bb99ff;'>s</span><span style='color:#cc88ff;'>t</span><span
                    style='color:#dd77ff;'>e</span><span style='color:#ff66ff;'>d</span></a></td>
        <td>17</td>
        <td>7817.373</td>
        <td>370.765</td>
    </tr>
    <tr>
        <td>321</td>
        <td><a href=players.php?pid=1362&edition=5><span style='color:#ff0000;'>モ</span><span
                    style='color:#ff8800;'>ェ</span><span style='color:#ffff00;'>乌</span></a></td>
        <td>17</td>
        <td>7819.800</td>
        <td>381.471</td>
    </tr>
    <tr>
        <td>322</td>
        <td><a href=players.php?pid=34410&edition=5>BusinessPengu</a></td>
        <td>17</td>
        <td>7822.493</td>
        <td>393.353</td>
    </tr>
    <tr>
        <td>323</td>
        <td><a href=players.php?pid=37414&edition=5>nsigfusson.</a></td>
        <td>17</td>
        <td>7825.573</td>
        <td>406.941</td>
    </tr>
    <tr>
        <td>324</td>
        <td><a href=players.php?pid=33759&edition=5><span style='color:#1155dd;'>P</span><span
                    style='color:#1166dd;'>I</span><span style='color:#2277dd;'>W</span><span
                    style='color:#3377dd;'>O</span><span style='color:#4488ee;'>!</span><span
                    style='color:#5599ee;'>&nbsp;</span><span style='color:#5599ee;'>v</span><span
                    style='color:#66aaee;'>n</span><span style='color:#77bbff;'>e</span><span
                    style='color:#88bbff;'>s</span><span style='color:#99ccff;'>s</span></a></td>
        <td>16</td>
        <td>7915.160</td>
        <td>227.312</td>
    </tr>
    <tr>
        <td>325</td>
        <td><a href=players.php?pid=36430&edition=5><span style='color:#ff9900;'>Z</span><span
                    style='color:#dd8800;'>y</span><span style='color:#aa6600;'>c</span><span
                    style='color:#885500;'>l</span><span style='color:#553300;'>o</span><span
                    style='color:#332200;'>n</span><span style='color:#000000;'>e</span></a></td>
        <td>16</td>
        <td>7918.613</td>
        <td>243.500</td>
    </tr>
    <tr>
        <td>326</td>
        <td><a href=players.php?pid=5467&edition=5><span style='color:#660000;'>V</span><span
                    style='color:#660044;'>r</span><span style='color:#660066;'>a</span><span
                    style='color:#660088;'>y</span><span style='color:#6600aa;'>Z</span></a></td>
        <td>16</td>
        <td>7920.027</td>
        <td>250.125</td>
    </tr>
    <tr>
        <td>327</td>
        <td><a href=players.php?pid=66851&edition=5><span style='color:#33ffff;'>R</span><span
                    style='color:#44eeff;'>e</span><span style='color:#55ddff;'>a</span><span
                    style='color:#66ccff;'>lS</span><span style='color:#77bbff;'>h</span><span
                    style='color:#88aaff;'>a</span><span style='color:#9999ff;'>d</span><span
                    style='color:#aa88ff;'>o</span><span style='color:#bb77ff;'>w</span><span
                    style='color:#cc66ff;'>Fa</span><span style='color:#dd55ff;'>n</span>0<span
                    style='color:#ff33ff;'>1&nbsp;:finish:</span></a></td>
        <td>16</td>
        <td>7922.027</td>
        <td>259.500</td>
    </tr>
    <tr>
        <td>328</td>
        <td><a href=players.php?pid=51780&edition=5>gatitech</a></td>
        <td>16</td>
        <td>7923.520</td>
        <td>266.500</td>
    </tr>
    <tr>
        <td>329</td>
        <td><a href=players.php?pid=52254&edition=5><span style='color:#cc0033;'>W</span><span
                    style='color:#991177;'>i</span><span style='color:#6622bb;'>k</span><span
                    style='color:#3333ff;'>k</span><span style='color:#3333ff;'>y</span><span
                    style='color:#222288;'>9</span><span style='color:#000000;'>6</span></a></td>
        <td>16</td>
        <td>7924.600</td>
        <td>271.562</td>
    </tr>
    <tr>
        <td>330</td>
        <td><a href=players.php?pid=114&edition=5>Jagger002</a></td>
        <td>16</td>
        <td>7925.840</td>
        <td>277.375</td>
    </tr>
    <tr>
        <td>331</td>
        <td><a href=players.php?pid=32784&edition=5><span style='color:#ff33cc;'>onion</span></a></td>
        <td>16</td>
        <td>7927.333</td>
        <td>284.375</td>
    </tr>
    <tr>
        <td>332</td>
        <td><a href=players.php?pid=25461&edition=5><span style='color:#ffffdd;font-weight:bold;'>I</span><span
                    style='color:#ffffee;font-weight:bold;'>nt</span><span
                    style='color:#ffffff;font-weight:bold;'>ax</span></a></td>
        <td>16</td>
        <td>7930.520</td>
        <td>299.312</td>
    </tr>
    <tr>
        <td>333</td>
        <td><a href=players.php?pid=36931&edition=5><span style='color:#66ccff;'>U</span><span
                    style='color:#88ccff;'>n</span><span style='color:#99bbff;'>k</span><span
                    style='color:#bbbbff;'>n</span><span style='color:#ccaaff;'>o</span><span
                    style='color:#eeaaff;'>w</span><span style='color:#ff99ff;'>n</span></a></td>
        <td>16</td>
        <td>7932.040</td>
        <td>306.438</td>
    </tr>
    <tr>
        <td>334</td>
        <td><a href=players.php?pid=51275&edition=5>Wes<span style='color:#bb77ff;'>tleee</span></a></td>
        <td>16</td>
        <td>7933.800</td>
        <td>314.688</td>
    </tr>
    <tr>
        <td>335</td>
        <td><a href=players.php?pid=68800&edition=5><span style='color:#cc0000;'>ant1socialik0_o</span></a></td>
        <td>16</td>
        <td>7935.373</td>
        <td>322.062</td>
    </tr>
    <tr>
        <td>336</td>
        <td><a href=players.php?pid=32702&edition=5>Josh_1963</a></td>
        <td>16</td>
        <td>7936.227</td>
        <td>326.062</td>
    </tr>
    <tr>
        <td>337</td>
        <td><a href=players.php?pid=66305&edition=5><span style='color:#ccffff;'>Bi</span><span
                    style='color:#ddffff;'>o&nbsp;A</span><span style='color:#eeffff;'>rca</span><span
                    style='color:#ffffff;'>ne</span></a></td>
        <td>16</td>
        <td>7937.813</td>
        <td>333.500</td>
    </tr>
    <tr>
        <td>338</td>
        <td><a href=players.php?pid=41730&edition=5><span style='color:#ff9933;'>r</span><span
                    style='color:#ffaa33;'>u</span><span style='color:#ffbb33;'>b</span><span
                    style='color:#ffcc33;'>b</span><span style='color:#ffdd33;'>e</span><span
                    style='color:#ffee33;'>r</span><span style='color:#ffff33;'>d</span><span
                    style='color:#ffff33;'>u</span><span style='color:#ffee33;'>c</span><span
                    style='color:#ffdd33;'>k</span><span style='color:#ffbb33;'>j</span><span
                    style='color:#ffaa33;'>e</span><span style='color:#ff9933;'>e</span></a></td>
        <td>16</td>
        <td>7937.933</td>
        <td>334.062</td>
    </tr>
    <tr>
        <td>339</td>
        <td><a href=players.php?pid=51763&edition=5>Fathom34</a></td>
        <td>16</td>
        <td>7940.253</td>
        <td>344.938</td>
    </tr>
    <tr>
        <td>340</td>
        <td><a href=players.php?pid=52567&edition=5><span style='color:#3366ee;'>Dan</span><span
                    style='color:#0088cc;'>On</span><span style='color:#00aaff;'>The</span><span
                    style='color:#22ccff;'>Moon</span></a></td>
        <td>16</td>
        <td>7940.680</td>
        <td>346.938</td>
    </tr>
    <tr>
        <td>341</td>
        <td><a href=players.php?pid=41129&edition=5><span style='color:#9933cc;'>H</span><span
                    style='color:#9944cc;'>e</span><span style='color:#aa55dd;'>ll</span><span
                    style='color:#bb66ee;'>d</span><span style='color:#bb77ee;'>e</span><span
                    style='color:#bb88ee;'>r</span><span style='color:#cc88ff;'>i</span><span
                    style='color:#cc99ff;'>s</span></a></td>
        <td>16</td>
        <td>7941.267</td>
        <td>349.688</td>
    </tr>
    <tr>
        <td>342</td>
        <td><a href=players.php?pid=69013&edition=5>FlimsyElbowTM</a></td>
        <td>16</td>
        <td>7943.347</td>
        <td>359.438</td>
    </tr>
    <tr>
        <td>343</td>
        <td><a href=players.php?pid=51700&edition=5><span style='color:#bb2299;'>G</span><span
                    style='color:#aa2299;'>o</span><span style='color:#9922aa;'>t</span><span
                    style='color:#8811bb;'>h</span><span style='color:#7711bb;'>M</span><span
                    style='color:#6611cc;'>o</span><span style='color:#5511cc;'>m</span><span
                    style='color:#4411dd;'>m</span><span style='color:#3311dd;'>y</span><span
                    style='color:#2200ee;'>&nbsp;</span><span style='color:#1100ee;'>:</span><span
                    style='color:#0000ff;'>3</span></a></td>
        <td>16</td>
        <td>7944.373</td>
        <td>364.250</td>
    </tr>
    <tr>
        <td>344</td>
        <td><a href=players.php?pid=31624&edition=5>Thanomrat</a></td>
        <td>16</td>
        <td>7944.813</td>
        <td>366.312</td>
    </tr>
    <tr>
        <td>345</td>
        <td><a href=players.php?pid=51798&edition=5>Smarmu</a></td>
        <td>16</td>
        <td>7945.093</td>
        <td>367.625</td>
    </tr>
    <tr>
        <td>346</td>
        <td><a href=players.php?pid=45754&edition=5><span style='color:#00ff00;'>mr</span><span
                    style='color:#000000;'>mac</span><span style='color:#00ff00;'>guy</span></a></td>
        <td>16</td>
        <td>7945.280</td>
        <td>368.500</td>
    </tr>
    <tr>
        <td>347</td>
        <td><a href=players.php?pid=11103&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;SirTalyon</span></a></td>
        <td>16</td>
        <td>7947.107</td>
        <td>377.062</td>
    </tr>
    <tr>
        <td>348</td>
        <td><a href=players.php?pid=69045&edition=5><span style='color:#66ff33;'>g</span><span
                    style='color:#339900;'>oo</span><span style='color:#66ff33;'>ps</span><span
                    style='color:#339900;'>TM</span></a></td>
        <td>16</td>
        <td>7952.613</td>
        <td>402.875</td>
    </tr>
    <tr>
        <td>349</td>
        <td><a href=players.php?pid=51621&edition=5><span style='color:#006600;'>K</span><span
                    style='color:#008855;'>a</span><span style='color:#009999;'>r</span><span
                    style='color:#009999;'>u</span><span style='color:#228822;'>m</span></a></td>
        <td>16</td>
        <td>7952.640</td>
        <td>403.000</td>
    </tr>
    <tr>
        <td>350</td>
        <td><a href=players.php?pid=7988&edition=5><span style='color:#33cc33;'>ゐ</span><span
                    style='color:#33aa33;'>〇</span><span style='color:#228822;'>ら</span><span
                    style='color:#228822;'>м</span><span style='color:#119922;'>入</span><span
                    style='color:#00aa22;'>Ň</span></a></td>
        <td>16</td>
        <td>7955.147</td>
        <td>414.750</td>
    </tr>
    <tr>
        <td>351</td>
        <td><a href=players.php?pid=98&edition=5><span style='color:#000000;'>&nbsp;/\dralonter</span></a></td>
        <td>16</td>
        <td>7955.187</td>
        <td>414.938</td>
    </tr>
    <tr>
        <td>352</td>
        <td><a href=players.php?pid=24168&edition=5>Holm2021</a></td>
        <td>16</td>
        <td>7957.453</td>
        <td>425.562</td>
    </tr>
    <tr>
        <td>353</td>
        <td><a href=players.php?pid=7876&edition=5><span style='color:#99ffff;'>q</span><span
                    style='color:#bbffbb;'>u</span><span style='color:#ccff88;'>o</span><span
                    style='color:#eeff44;'>ｲ</span><span style='color:#ffff00;'>.</span></a></td>
        <td>16</td>
        <td>7958.027</td>
        <td>428.250</td>
    </tr>
    <tr>
        <td>354</td>
        <td><a href=players.php?pid=6189&edition=5>TwinTM</a></td>
        <td>16</td>
        <td>7959.227</td>
        <td>433.875</td>
    </tr>
    <tr>
        <td>355</td>
        <td><a href=players.php?pid=66117&edition=5>C<span style='font-weight:bold;'>THC&nbsp;:xdd:</span></a></td>
        <td>16</td>
        <td>7959.427</td>
        <td>434.812</td>
    </tr>
    <tr>
        <td>356</td>
        <td><a href=players.php?pid=9064&edition=5>romchampi1</a></td>
        <td>16</td>
        <td>7960.147</td>
        <td>438.188</td>
    </tr>
    <tr>
        <td>357</td>
        <td><a href=players.php?pid=16183&edition=5><span style='color:#ff8800;font-weight:bold;'>T</span><span
                    style='color:#ff9900;font-weight:bold;'>o</span><span
                    style='color:#ffaa00;font-weight:bold;'>t</span><span
                    style='color:#ffaa00;font-weight:bold;'>o</span><span style='font-weight:bold;'>🔎</span></a></td>
        <td>16</td>
        <td>7965.613</td>
        <td>463.812</td>
    </tr>
    <tr>
        <td>358</td>
        <td><a href=players.php?pid=34136&edition=5>Koble</a></td>
        <td>15</td>
        <td>8036.227</td>
        <td>181.133</td>
    </tr>
    <tr>
        <td>359</td>
        <td><a href=players.php?pid=17669&edition=5>irisTM.</a></td>
        <td>15</td>
        <td>8038.800</td>
        <td>194.000</td>
    </tr>
    <tr>
        <td>360</td>
        <td><a href=players.php?pid=30623&edition=5>jedrzej007</a></td>
        <td>15</td>
        <td>8049.827</td>
        <td>249.133</td>
    </tr>
    <tr>
        <td>361</td>
        <td><a href=players.php?pid=15506&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>|&nbsp;Artisse</span></a></td>
        <td>15</td>
        <td>8052.667</td>
        <td>263.333</td>
    </tr>
    <tr>
        <td>362</td>
        <td><a href=players.php?pid=10647&edition=5><span
                    style='color:#66ff99;font-style:italic;font-weight:bold;'>S</span><span
                    style='color:#77aabb;font-style:italic;font-weight:bold;'>C</span><span
                    style='color:#8855dd;font-style:italic;font-weight:bold;'>H</span><span
                    style='color:#9900ff;font-style:italic;font-weight:bold;'>W</span><span
                    style='color:#9900ff;font-style:italic;font-weight:bold;'>A</span><span
                    style='color:#bb22ff;font-style:italic;font-weight:bold;'>B</span><span
                    style='color:#dd44ff;font-style:italic;font-weight:bold;'>B</span><span
                    style='color:#ff66ff;font-style:italic;font-weight:bold;'>A</span></a></td>
        <td>15</td>
        <td>8054.187</td>
        <td>270.933</td>
    </tr>
    <tr>
        <td>363</td>
        <td><a href=players.php?pid=4951&edition=5><span style='color:#ff77dd;'>S</span><span
                    style='color:#ff88ee;'>h</span><span style='color:#ffaaee;'>yf</span><span
                    style='color:#ffbbee;'>i</span><span style='color:#ffddff;'>r</span><span
                    style='color:#ffffff;'>e</span></a></td>
        <td>15</td>
        <td>8061.627</td>
        <td>308.133</td>
    </tr>
    <tr>
        <td>364</td>
        <td><a href=players.php?pid=2005&edition=5><span style='color:#ff0000;font-style:italic;'>C</span><span
                    style='color:#ffcc00;font-style:italic;'>h</span><span
                    style='color:#33ff00;font-style:italic;'>r</span><span
                    style='color:#0099ff;font-style:italic;'>o</span><span
                    style='color:#9933ff;font-style:italic;'>m</span><span
                    style='color:#ff00cc;font-style:italic;'>a&nbsp;:POGGERS:</span></a></td>
        <td>15</td>
        <td>8064.813</td>
        <td>324.067</td>
    </tr>
    <tr>
        <td>365</td>
        <td><a href=players.php?pid=52117&edition=5><span style='color:#ff9900;'>F</span><span
                    style='color:#ff8833;'>l</span><span style='color:#ff6655;'>o</span><span
                    style='color:#ff5588;'>s</span><span style='color:#ff33aa;'>s</span><span
                    style='color:#ff22dd;'>i</span><span style='color:#ff00ff;'>n</span></a></td>
        <td>15</td>
        <td>8066.053</td>
        <td>330.267</td>
    </tr>
    <tr>
        <td>366</td>
        <td><a href=players.php?pid=51680&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Fenrir&nbsp;C-137</span></a></td>
        <td>15</td>
        <td>8068.013</td>
        <td>340.067</td>
    </tr>
    <tr>
        <td>367</td>
        <td><a href=players.php?pid=18923&edition=5><span style='color:#ff0000;'>H</span><span
                    style='color:#cc1133;'>a</span><span style='color:#991166;'>n</span><span
                    style='color:#662299;'>n</span><span style='color:#3322cc;'>o</span><span
                    style='color:#0033ff;'>f</span><span style='color:#0033ff;'>a</span><span
                    style='color:#3355ff;'>g</span><span style='color:#6688ff;'>a</span><span
                    style='color:#99aaff;'>s</span><span style='color:#ccddff;'>t</span><span
                    style='color:#ffffff;'>a</span></a></td>
        <td>15</td>
        <td>8068.880</td>
        <td>344.400</td>
    </tr>
    <tr>
        <td>368</td>
        <td><a href=players.php?pid=8189&edition=5>monkacat1992</a></td>
        <td>15</td>
        <td>8069.760</td>
        <td>348.800</td>
    </tr>
    <tr>
        <td>369</td>
        <td><a href=players.php?pid=37573&edition=5><span style='color:#3333ff;'>S</span><span
                    style='color:#2255ff;'>e</span><span style='color:#1177ff;'>a</span><span
                    style='color:#0099ff;'>l</span></a></td>
        <td>15</td>
        <td>8070.507</td>
        <td>352.533</td>
    </tr>
    <tr>
        <td>370</td>
        <td><a href=players.php?pid=4680&edition=5><span style='font-weight:bold;'>:keepingcool:</span></a></td>
        <td>15</td>
        <td>8070.627</td>
        <td>353.133</td>
    </tr>
    <tr>
        <td>371</td>
        <td><a href=players.php?pid=52843&edition=5>Pascauuu</a></td>
        <td>15</td>
        <td>8074.040</td>
        <td>370.200</td>
    </tr>
    <tr>
        <td>372</td>
        <td><a href=players.php?pid=32560&edition=5>hey_there_son</a></td>
        <td>15</td>
        <td>8076.627</td>
        <td>383.133</td>
    </tr>
    <tr>
        <td>373</td>
        <td><a href=players.php?pid=51918&edition=5>MangeMoiLeBolet</a></td>
        <td>15</td>
        <td>8080.200</td>
        <td>401.000</td>
    </tr>
    <tr>
        <td>374</td>
        <td><a href=players.php?pid=11508&edition=5>God_Uperman</a></td>
        <td>15</td>
        <td>8082.267</td>
        <td>411.333</td>
    </tr>
    <tr>
        <td>375</td>
        <td><a href=players.php?pid=25879&edition=5><span style='color:#99ff66;'>&nbsp;ﾌos爪y</span></a></td>
        <td>15</td>
        <td>8082.920</td>
        <td>414.600</td>
    </tr>
    <tr>
        <td>376</td>
        <td><a href=players.php?pid=29307&edition=5><span style='color:#0000ff;'>N&lt;3&nbsp;</span></a></td>
        <td>15</td>
        <td>8086.813</td>
        <td>434.067</td>
    </tr>
    <tr>
        <td>377</td>
        <td><a href=players.php?pid=9940&edition=5>YataTM</a></td>
        <td>15</td>
        <td>8088.373</td>
        <td>441.867</td>
    </tr>
    <tr>
        <td>378</td>
        <td><a href=players.php?pid=16786&edition=5><span style='color:#440066;font-style:italic;'>..soli</span></a>
        </td>
        <td>15</td>
        <td>8095.827</td>
        <td>479.133</td>
    </tr>
    <tr>
        <td>379</td>
        <td><a href=players.php?pid=69840&edition=5><span style='color:#ff9900;'>k</span><span
                    style='color:#ff6600;'>r</span><span style='color:#ff3300;'>s</span></a></td>
        <td>15</td>
        <td>8104.307</td>
        <td>521.533</td>
    </tr>
    <tr>
        <td>380</td>
        <td><a href=players.php?pid=30887&edition=5><span style='color:#ff0000;'>M</span><span
                    style='color:#dd0022;'>a</span><span style='color:#bb1144;'>k</span><span
                    style='color:#991166;'>o</span><span style='color:#882288;'>v</span><span
                    style='color:#662299;'>e</span><span style='color:#4422bb;'>c</span><span
                    style='color:#2233dd;'>5</span><span style='color:#0033ff;'>5</span></a></td>
        <td>14</td>
        <td>8174.733</td>
        <td>221.786</td>
    </tr>
    <tr>
        <td>381</td>
        <td><a href=players.php?pid=47114&edition=5><span style='color:#ffffff;'>yorid.</span><span
                    style='color:#ccccff;'>K</span><span style='color:#ccccff;'>a</span><span
                    style='color:#bbbbff;'>c</span><span style='color:#bb99ff;'>c</span><span
                    style='color:#aa88ff;'>h</span><span style='color:#9966ff;'>i</span></a></td>
        <td>14</td>
        <td>8183.120</td>
        <td>266.714</td>
    </tr>
    <tr>
        <td>382</td>
        <td><a href=players.php?pid=161&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='color:#00ffff;'>乙</span><span
                    style='color:#00eedd;'>e</span><span style='color:#00ddaa;'>e</span><span
                    style='color:#00cc88;'>m</span><span style='color:#00bb55;'>u</span><span
                    style='color:#00aa33;'>i</span><span style='color:#009900;'>s</span></a></td>
        <td>14</td>
        <td>8184.373</td>
        <td>273.429</td>
    </tr>
    <tr>
        <td>383</td>
        <td><a href=players.php?pid=37176&edition=5><span style='color:#bb2200;'>Get</span><span
                    style='color:#ffffff;'>Me</span><span style='color:#bb2200;'>Out</span></a></td>
        <td>14</td>
        <td>8184.653</td>
        <td>274.929</td>
    </tr>
    <tr>
        <td>384</td>
        <td><a href=players.php?pid=70328&edition=5>jantronix1</a></td>
        <td>14</td>
        <td>8186.587</td>
        <td>285.286</td>
    </tr>
    <tr>
        <td>385</td>
        <td><a href=players.php?pid=12696&edition=5>Yikh00</a></td>
        <td>14</td>
        <td>8186.600</td>
        <td>285.357</td>
    </tr>
    <tr>
        <td>386</td>
        <td><a href=players.php?pid=8276&edition=5>SneakyyTM</a></td>
        <td>14</td>
        <td>8187.013</td>
        <td>287.571</td>
    </tr>
    <tr>
        <td>387</td>
        <td><a href=players.php?pid=47181&edition=5>m3gachonk</a></td>
        <td>14</td>
        <td>8191.573</td>
        <td>312.000</td>
    </tr>
    <tr>
        <td>388</td>
        <td><a href=players.php?pid=11&edition=5>Burd</a></td>
        <td>14</td>
        <td>8192.267</td>
        <td>315.714</td>
    </tr>
    <tr>
        <td>389</td>
        <td><a href=players.php?pid=25129&edition=5>HimaJuwston</a></td>
        <td>14</td>
        <td>8192.480</td>
        <td>316.857</td>
    </tr>
    <tr>
        <td>390</td>
        <td><a href=players.php?pid=65&edition=5>AlekBees</a></td>
        <td>14</td>
        <td>8193.533</td>
        <td>322.500</td>
    </tr>
    <tr>
        <td>391</td>
        <td><a href=players.php?pid=54886&edition=5>cnromano</a></td>
        <td>14</td>
        <td>8193.720</td>
        <td>323.500</td>
    </tr>
    <tr>
        <td>392</td>
        <td><a href=players.php?pid=66114&edition=5><span
                    style='color:#ffccff;font-weight:bold;'>BoysMilkDrinker</span></a></td>
        <td>14</td>
        <td>8194.773</td>
        <td>329.143</td>
    </tr>
    <tr>
        <td>393</td>
        <td><a href=players.php?pid=35374&edition=5><span style='color:#ccff00;'>Br</span><span
                    style='color:#ddff00;'>ing</span><span style='color:#eeff00;'>er30</span><span
                    style='color:#ffff00;'>00</span></a></td>
        <td>14</td>
        <td>8195.013</td>
        <td>330.429</td>
    </tr>
    <tr>
        <td>394</td>
        <td><a href=players.php?pid=72048&edition=5>jjjude45</a></td>
        <td>14</td>
        <td>8195.307</td>
        <td>332.000</td>
    </tr>
    <tr>
        <td>395</td>
        <td><a href=players.php?pid=35601&edition=5>Sylrax&nbsp;:hylis:</a></td>
        <td>14</td>
        <td>8195.880</td>
        <td>335.071</td>
    </tr>
    <tr>
        <td>396</td>
        <td><a href=players.php?pid=21423&edition=5><span style='color:#330066;'>D</span><span
                    style='color:#660099;'>ir</span><span style='color:#9900ff;'>t</span><span
                    style='color:#9966ff;'>y</span><span style='color:#6600ff;'>D</span><span
                    style='color:#6633ff;'>a</span><span style='color:#3300ff;'>n</span><span
                    style='color:#000099;'>n</span><span style='color:#000066;'>y</span></a></td>
        <td>14</td>
        <td>8197.373</td>
        <td>343.071</td>
    </tr>
    <tr>
        <td>397</td>
        <td><a href=players.php?pid=62677&edition=5><span
                    style='color:#33ff66;font-style:italic;font-weight:bold;'>&nbsp;KEYS</span></a></td>
        <td>14</td>
        <td>8200.813</td>
        <td>361.500</td>
    </tr>
    <tr>
        <td>398</td>
        <td><a href=players.php?pid=37854&edition=5>Zower98</a></td>
        <td>14</td>
        <td>8203.960</td>
        <td>378.357</td>
    </tr>
    <tr>
        <td>399</td>
        <td><a href=players.php?pid=43587&edition=5><span style='color:#6699cc;'>b</span><span
                    style='color:#55aacc;'>ea</span><span style='color:#44bbcc;'>sa</span><span
                    style='color:#33cccc;'>s</span><span style='color:#33cccc;'>d</span><span
                    style='color:#22ccaa;'>a</span><span style='color:#22cc88;'>f</span><span
                    style='color:#11cc55;'>T</span><span style='color:#00cc33;'>M</span></a></td>
        <td>14</td>
        <td>8204.547</td>
        <td>381.500</td>
    </tr>
    <tr>
        <td>400</td>
        <td><a href=players.php?pid=32305&edition=5>akimaNN7</a></td>
        <td>14</td>
        <td>8205.720</td>
        <td>387.786</td>
    </tr>
    <tr>
        <td>401</td>
        <td><a href=players.php?pid=66260&edition=5>CustomTX</a></td>
        <td>14</td>
        <td>8208.400</td>
        <td>402.143</td>
    </tr>
    <tr>
        <td>402</td>
        <td><a href=players.php?pid=42339&edition=5>RobeTM</a></td>
        <td>14</td>
        <td>8209.320</td>
        <td>407.071</td>
    </tr>
    <tr>
        <td>403</td>
        <td><a href=players.php?pid=29935&edition=5><span style='color:#ee8800;'>k</span><span
                    style='color:#eecc00;'>r</span><span style='color:#ffffff;'>y</span><span
                    style='color:#55aadd;'>o</span><span style='color:#113355;'>h</span><span
                    style='color:#000000;'>_</span></a></td>
        <td>14</td>
        <td>8211.160</td>
        <td>416.929</td>
    </tr>
    <tr>
        <td>404</td>
        <td><a href=players.php?pid=19509&edition=5>Knutha</a></td>
        <td>14</td>
        <td>8211.240</td>
        <td>417.357</td>
    </tr>
    <tr>
        <td>405</td>
        <td><a href=players.php?pid=67235&edition=5><span style='color:#ee55cc;'>m</span><span
                    style='color:#ee66cc;'>o</span><span style='color:#ee77cc;'>s</span><span
                    style='color:#ee88cc;'>h</span><span style='color:#ee99cc;'>i</span><span
                    style='color:#eeaacc;'>i</span><span style='color:#eebbcc;'>c</span><span
                    style='color:#eecccc;'>s.</span><span style='color:#ccccff;'>K</span><span
                    style='color:#ccccff;'>a</span><span style='color:#bbbbff;'>c</span><span
                    style='color:#bb99ff;'>c</span><span style='color:#aa88ff;'>h</span><span
                    style='color:#9966ff;'>i</span></a></td>
        <td>14</td>
        <td>8213.227</td>
        <td>428.000</td>
    </tr>
    <tr>
        <td>406</td>
        <td><a href=players.php?pid=17671&edition=5><span style='color:#cc2222;'>A</span><span
                    style='color:#aa2222;'>r</span><span style='color:#882222;'>k</span><span
                    style='color:#661122;'>a</span><span style='color:#441133;'>n</span><span
                    style='color:#221133;'>o</span></a></td>
        <td>14</td>
        <td>8215.693</td>
        <td>441.214</td>
    </tr>
    <tr>
        <td>407</td>
        <td><a href=players.php?pid=48751&edition=5><span style='color:#660099;'>ThePop</span></a></td>
        <td>14</td>
        <td>8216.427</td>
        <td>445.143</td>
    </tr>
    <tr>
        <td>408</td>
        <td><a href=players.php?pid=60808&edition=5>vizon320</a></td>
        <td>14</td>
        <td>8217.427</td>
        <td>450.500</td>
    </tr>
    <tr>
        <td>409</td>
        <td><a href=players.php?pid=38664&edition=5><span style='color:#bbeeee;'>f</span><span
                    style='color:#aadddd;'>i</span><span style='color:#99cccc;'>n</span><span
                    style='color:#88bbbb;'>s</span><span style='color:#88aaaa;'>&nbsp;</span><span
                    style='color:#779999;'>[</span>0<span style='color:#556666;'>]</span><span
                    style='color:#445555;'>&nbsp;</span><span style='color:#334444;'>s</span><span
                    style='color:#333333;'>k</span><span style='color:#222222;'>i</span><span
                    style='color:#111111;'>l</span><span style='color:#000000;'>l</span></a></td>
        <td>14</td>
        <td>8217.573</td>
        <td>451.286</td>
    </tr>
    <tr>
        <td>410</td>
        <td><a href=players.php?pid=50759&edition=5>Meldys</a></td>
        <td>14</td>
        <td>8220.547</td>
        <td>467.214</td>
    </tr>
    <tr>
        <td>411</td>
        <td><a href=players.php?pid=66167&edition=5>K:e:b:owo:TM</a></td>
        <td>14</td>
        <td>8220.680</td>
        <td>467.929</td>
    </tr>
    <tr>
        <td>412</td>
        <td><a href=players.php?pid=24983&edition=5><span style='color:#000000;font-weight:bold;'>~</span><span
                    style='color:#009933;font-weight:bold;'>x</span><span
                    style='color:#118844;font-weight:bold;'>o</span><span
                    style='color:#228855;font-weight:bold;'>s</span><span
                    style='color:#227755;font-weight:bold;'>a</span><span
                    style='color:#336666;font-weight:bold;'>r</span><span
                    style='color:#000000;font-weight:bold;'>~</span></a></td>
        <td>14</td>
        <td>8227.133</td>
        <td>502.500</td>
    </tr>
    <tr>
        <td>413</td>
        <td><a href=players.php?pid=21592&edition=5><span style='color:#9900ff;'>S</span><span
                    style='color:#7733ff;'>i</span><span style='color:#5566ff;'>z</span><span
                    style='color:#4499ff;'>e</span><span style='color:#22ccff;'>4</span><span
                    style='color:#00ffff;'>5</span></a></td>
        <td>14</td>
        <td>8237.973</td>
        <td>560.571</td>
    </tr>
    <tr>
        <td>414</td>
        <td><a href=players.php?pid=1306&edition=5><span
                    style='color:#00ff00;font-weight:bold;'>f:e:lalex&nbsp;the&nbsp;failer</span></a></td>
        <td>13</td>
        <td>8306.040</td>
        <td>227.154</td>
    </tr>
    <tr>
        <td>415</td>
        <td><a href=players.php?pid=10685&edition=5>Fisken_TM</a></td>
        <td>13</td>
        <td>8311.773</td>
        <td>260.231</td>
    </tr>
    <tr>
        <td>416</td>
        <td><a href=players.php?pid=11099&edition=5>TiToch22</a></td>
        <td>13</td>
        <td>8312.027</td>
        <td>261.692</td>
    </tr>
    <tr>
        <td>417</td>
        <td><a href=players.php?pid=15025&edition=5>Persiano</a></td>
        <td>13</td>
        <td>8312.800</td>
        <td>266.154</td>
    </tr>
    <tr>
        <td>418</td>
        <td><a href=players.php?pid=30541&edition=5><span style='color:#6600ff;'>A</span><span
                    style='color:#7700ff;'>tr</span><span style='color:#8800ff;'>ej</span><span
                    style='color:#9900ff;'>oe&nbsp;:peepoblanket:&nbsp;</span></a></td>
        <td>13</td>
        <td>8312.840</td>
        <td>266.385</td>
    </tr>
    <tr>
        <td>419</td>
        <td><a href=players.php?pid=22286&edition=5><span style='color:#aaffcc;'>alexboi</span></a></td>
        <td>13</td>
        <td>8314.933</td>
        <td>278.462</td>
    </tr>
    <tr>
        <td>420</td>
        <td><a href=players.php?pid=65896&edition=5>k<span style='font-style:italic;font-weight:bold;'>*</span></a></td>
        <td>13</td>
        <td>8315.307</td>
        <td>280.615</td>
    </tr>
    <tr>
        <td>421</td>
        <td><a href=players.php?pid=829&edition=5>bitausaurus</a></td>
        <td>13</td>
        <td>8318.373</td>
        <td>298.308</td>
    </tr>
    <tr>
        <td>422</td>
        <td><a href=players.php?pid=15242&edition=5><span style='color:#33ffff;'>s</span><span
                    style='color:#22ccff;'>k</span><span style='color:#2299ff;'>o</span><span
                    style='color:#1166ff;'>t</span><span style='color:#1133ff;'>o</span><span
                    style='color:#0000ff;'>s</span></a></td>
        <td>13</td>
        <td>8321.227</td>
        <td>314.769</td>
    </tr>
    <tr>
        <td>423</td>
        <td><a href=players.php?pid=27458&edition=5>Phase&nbsp;meat&nbsp;:xdd:</a></td>
        <td>13</td>
        <td>8324.267</td>
        <td>332.308</td>
    </tr>
    <tr>
        <td>424</td>
        <td><a href=players.php?pid=51734&edition=5>stari&nbsp;:smirkcat:</a></td>
        <td>13</td>
        <td>8324.373</td>
        <td>332.923</td>
    </tr>
    <tr>
        <td>425</td>
        <td><a href=players.php?pid=67679&edition=5><span style='color:#000000;font-weight:bold;'>N</span><span
                    style='color:#ffffff;font-weight:bold;'>M</span><span
                    style='color:#dd1133;font-weight:bold;'>E</span></a></td>
        <td>13</td>
        <td>8326.093</td>
        <td>342.846</td>
    </tr>
    <tr>
        <td>426</td>
        <td><a href=players.php?pid=66152&edition=5><span style='color:#000055;'>S</span><span
                    style='color:#110055;'>u</span><span style='color:#220044;'>c</span><span
                    style='color:#220044;'>k</span><span style='color:#330044;'>i</span><span
                    style='color:#440033;'>e</span><span style='color:#550033;'>s</span><span
                    style='color:#550033;'>t</span></a></td>
        <td>13</td>
        <td>8327.400</td>
        <td>350.385</td>
    </tr>
    <tr>
        <td>427</td>
        <td><a href=players.php?pid=51114&edition=5>samuelhip</a></td>
        <td>13</td>
        <td>8328.600</td>
        <td>357.308</td>
    </tr>
    <tr>
        <td>428</td>
        <td><a href=players.php?pid=33219&edition=5><span style='color:#00ccff;'>N</span><span
                    style='color:#33aaff;'>e</span><span style='color:#6677ff;'>b</span><span
                    style='color:#9955ff;'>u</span><span style='color:#cc22ff;'>l</span><span
                    style='color:#ff00ff;'>a</span></a></td>
        <td>13</td>
        <td>8329.613</td>
        <td>363.154</td>
    </tr>
    <tr>
        <td>429</td>
        <td><a href=players.php?pid=28472&edition=5><span style='color:#ddbb22;'>H</span><span
                    style='color:#dd9922;'>e</span><span style='color:#cc8822;'>r</span><span
                    style='color:#bb6622;'>m</span><span style='color:#cc6600;'>.</span><span
                    style='color:#ffdd33;'>➟</span></a></td>
        <td>13</td>
        <td>8329.933</td>
        <td>365.000</td>
    </tr>
    <tr>
        <td>430</td>
        <td><a href=players.php?pid=883&edition=5><span style='color:#774411;font-weight:bold;'>ֽ</span><span
                    style='color:#00ff11;font-weight:bold;'>▲</span></a></td>
        <td>13</td>
        <td>8330.107</td>
        <td>366.000</td>
    </tr>
    <tr>
        <td>431</td>
        <td><a href=players.php?pid=44393&edition=5><span style='color:#00ffff;'>C</span><span
                    style='color:#44ccff;'>a</span><span style='color:#8899ff;'>y</span><span
                    style='color:#bb66ff;'>c</span><span style='color:#ff33ff;'>i</span><span
                    style='color:#ff33ff;'>R</span><span style='color:#ff33ee;'>e</span><span
                    style='color:#ee33cc;'>m</span><span style='color:#ee22bb;'>z</span><span
                    style='color:#dd2299;'>i</span></a></td>
        <td>13</td>
        <td>8330.333</td>
        <td>367.308</td>
    </tr>
    <tr>
        <td>432</td>
        <td><a href=players.php?pid=33284&edition=5>diBestA</a></td>
        <td>13</td>
        <td>8330.333</td>
        <td>367.308</td>
    </tr>
    <tr>
        <td>433</td>
        <td><a href=players.php?pid=50539&edition=5><span style='color:#ee0000;'>P</span><span
                    style='color:#cc2211;'>u</span><span style='color:#aa4433;'>u</span><span
                    style='color:#886644;'>p</span><span style='color:#669955;'>y</span><span
                    style='color:#44bb66;'>c</span><span style='color:#22dd88;'>h</span><span
                    style='color:#00ff99;'></span></a></td>
        <td>13</td>
        <td>8331.533</td>
        <td>374.231</td>
    </tr>
    <tr>
        <td>434</td>
        <td><a href=players.php?pid=31547&edition=5><span style='color:#cccc00;'>&epsilon;</span><span
                    style='color:#99ee88;'>Ļ</span><span style='color:#66ffff;'>ね</span><span
                    style='color:#66ffff;'>ě</span><span style='color:#ff6666;'>ท</span></a></td>
        <td>13</td>
        <td>8333.440</td>
        <td>385.231</td>
    </tr>
    <tr>
        <td>435</td>
        <td><a href=players.php?pid=64570&edition=5>Zeota</a></td>
        <td>13</td>
        <td>8334.613</td>
        <td>392.000</td>
    </tr>
    <tr>
        <td>436</td>
        <td><a href=players.php?pid=853&edition=5>VDS_Tobi</a></td>
        <td>13</td>
        <td>8334.933</td>
        <td>393.846</td>
    </tr>
    <tr>
        <td>437</td>
        <td><a href=players.php?pid=29436&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ff9900;'>E</span><span style='color:#ffcc00;'>d</span><span
                    style='color:#ffff00;'>i</span><span style='color:#ffff00;'>xot</span></a></td>
        <td>13</td>
        <td>8335.480</td>
        <td>397.000</td>
    </tr>
    <tr>
        <td>438</td>
        <td><a href=players.php?pid=36560&edition=5><span style='font-style:italic;'>&nbsp;</span><span
                    style='color:#ff0000;font-style:italic;'>Fully</span><span
                    style='color:#888888;font-style:italic;'>Dynamic</span></a></td>
        <td>13</td>
        <td>8335.693</td>
        <td>398.231</td>
    </tr>
    <tr>
        <td>439</td>
        <td><a href=players.php?pid=22007&edition=5><span style='color:#ff0000;'>S</span><span
                    style='color:#ff0022;'>o</span><span style='color:#ff0033;'>c</span><span
                    style='color:#ff0055;'>k</span><span style='color:#ff0066;'>a</span><span
                    style='color:#ff0088;'>m</span><span style='color:#ff0099;'>p</span></a></td>
        <td>13</td>
        <td>8337.560</td>
        <td>409.000</td>
    </tr>
    <tr>
        <td>440</td>
        <td><a href=players.php?pid=31738&edition=5>ShadowYEET17</a></td>
        <td>13</td>
        <td>8340.333</td>
        <td>425.000</td>
    </tr>
    <tr>
        <td>441</td>
        <td><a href=players.php?pid=32286&edition=5><span style='color:#000000;'>R</span><span
                    style='color:#444444;'>a</span><span style='color:#777777;'>c</span><span
                    style='color:#777777;'>z</span><span style='color:#bbbbbb;'>e</span><span
                    style='color:#ffffff;'>j</span></a></td>
        <td>13</td>
        <td>8342.133</td>
        <td>435.385</td>
    </tr>
    <tr>
        <td>442</td>
        <td><a href=players.php?pid=21296&edition=5>FreeThrash</a></td>
        <td>13</td>
        <td>8342.760</td>
        <td>439.000</td>
    </tr>
    <tr>
        <td>443</td>
        <td><a href=players.php?pid=20471&edition=5><span style='color:#33ffff;'>A</span><span
                    style='color:#55ddff;'>e</span><span style='color:#66aaff;'>l</span><span
                    style='color:#8888ff;'>e</span><span style='color:#9955ff;'>r</span><span
                    style='color:#bb33ff;'>u</span><span style='color:#cc00ff;'>s</span></a></td>
        <td>13</td>
        <td>8343.427</td>
        <td>442.846</td>
    </tr>
    <tr>
        <td>444</td>
        <td><a href=players.php?pid=66833&edition=5><span style='color:#00ccff;'>C</span><span
                    style='color:#11ccff;'>y</span><span style='color:#33ddff;'>c</span><span
                    style='color:#44ddff;'>l</span><span style='color:#55ddff;'>o</span><span
                    style='color:#77ddff;'>p</span><span style='color:#88eeff;'>s</span><span
                    style='color:#aaeeff;'>S</span><span style='color:#bbeeff;'>t</span><span
                    style='color:#cceeff;'>e</span><span style='color:#eeffff;'>v</span><span
                    style='color:#ffffff;'>e&nbsp;:EYES:-1</span></a></td>
        <td>13</td>
        <td>8345.400</td>
        <td>454.231</td>
    </tr>
    <tr>
        <td>445</td>
        <td><a href=players.php?pid=68047&edition=5>Zodwin</a></td>
        <td>13</td>
        <td>8348.120</td>
        <td>469.923</td>
    </tr>
    <tr>
        <td>446</td>
        <td><a href=players.php?pid=66204&edition=5>FullSendSamu</a></td>
        <td>13</td>
        <td>8350.267</td>
        <td>482.308</td>
    </tr>
    <tr>
        <td>447</td>
        <td><a href=players.php?pid=500&edition=5><span style='color:#0000cc;'>Ł</span><span
                    style='color:#0011dd;'>&sigma;</span><span style='color:#0022dd;'>&alpha;</span><span
                    style='color:#0033ee;'>ȡ</span><span style='color:#0044ee;'>ϊ</span><span
                    style='color:#0055ff;'>ก</span><span style='color:#0066ff;'>ǥ&nbsp;</span><span
                    style='color:#66ffff;'>々&nbsp;</span><span style='color:#000000;'>&not;&nbsp;</span><span
                    style='color:#888888;font-style:italic;font-weight:bold;'>Ѵ&Sigma;Ѵ&theta;&trade;</span></a></td>
        <td>13</td>
        <td>8353.067</td>
        <td>498.462</td>
    </tr>
    <tr>
        <td>448</td>
        <td><a href=players.php?pid=29159&edition=5><span style='color:#9922ff;'>Kristiano&nbsp;:owo:</span></a></td>
        <td>13</td>
        <td>8354.067</td>
        <td>504.231</td>
    </tr>
    <tr>
        <td>449</td>
        <td><a href=players.php?pid=6468&edition=5><span style='color:#ff00cc;'>l</span><span
                    style='color:#8866ee;'>l</span><span style='color:#00ccff;'>a</span><span
                    style='color:#00ccff;'>i</span><span style='color:#00ff66;'>N</span></a></td>
        <td>13</td>
        <td>8356.893</td>
        <td>520.538</td>
    </tr>
    <tr>
        <td>450</td>
        <td><a href=players.php?pid=39450&edition=5>LokoEx</a></td>
        <td>13</td>
        <td>8358.320</td>
        <td>528.769</td>
    </tr>
    <tr>
        <td>451</td>
        <td><a href=players.php?pid=51945&edition=5>DivineCarly_</a></td>
        <td>13</td>
        <td>8363.947</td>
        <td>561.231</td>
    </tr>
    <tr>
        <td>452</td>
        <td><a href=players.php?pid=8772&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='color:#3366cc;font-style:italic;'>ɀe</span><span
                    style='color:#3377dd;font-style:italic;'>nt</span><span
                    style='color:#3388ee;font-style:italic;'>ri</span><span
                    style='color:#3399ff;font-style:italic;'>an</span></a></td>
        <td>12</td>
        <td>8432.720</td>
        <td>204.500</td>
    </tr>
    <tr>
        <td>453</td>
        <td><a href=players.php?pid=43648&edition=5>Schmaniol</a></td>
        <td>12</td>
        <td>8436.693</td>
        <td>229.333</td>
    </tr>
    <tr>
        <td>454</td>
        <td><a href=players.php?pid=9&edition=5>Kuj</a></td>
        <td>12</td>
        <td>8438.000</td>
        <td>237.500</td>
    </tr>
    <tr>
        <td>455</td>
        <td><a href=players.php?pid=35522&edition=5><span style='color:#000000;'>G</span><span
                    style='color:#111100;'>a</span><span style='color:#221100;'>&beta;</span><span
                    style='color:#442200;'>&beta;</span><span style='color:#552200;'>i</span><span
                    style='color:#663300;'>a</span><span style='color:#663300;'>&eta;</span><span
                    style='color:#772200;'>aJ</span><span style='color:#881100;'>o&eta;</span><span
                    style='color:#990000;'>s</span></a></td>
        <td>12</td>
        <td>8440.173</td>
        <td>251.083</td>
    </tr>
    <tr>
        <td>456</td>
        <td><a href=players.php?pid=51848&edition=5>upturnedship</a></td>
        <td>12</td>
        <td>8441.013</td>
        <td>256.333</td>
    </tr>
    <tr>
        <td>457</td>
        <td><a href=players.php?pid=52244&edition=5><span style='color:#ff0000;'>R</span><span
                    style='color:#ff0000;'>u</span><span style='color:#ff0000;'>b</span><span
                    style='color:#ff0000;'>e</span><span style='color:#ff0000;'>n</span><span
                    style='color:#ff0000;'>o</span><span style='color:#ff0000;'>f</span><span
                    style='color:#ff0000;'>s</span><span style='color:#ff0000;'>k</span><span
                    style='color:#ff0000;'>i</span><span style='color:#000000;'>-</span><span
                    style='color:#000000;'>2</span><span style='color:#000000;'>3</span></a></td>
        <td>12</td>
        <td>8444.747</td>
        <td>279.667</td>
    </tr>
    <tr>
        <td>458</td>
        <td><a href=players.php?pid=254&edition=5><span style='color:#663300;'>D</span><span
                    style='color:#884411;'>o</span><span style='color:#aa5511;'>d</span><span
                    style='color:#bb7722;'>e</span><span style='color:#dd8822;'>c</span><span
                    style='color:#ff9933;'>a</span><span style='color:#ff9933;'>h</span><span
                    style='color:#dd8822;'>e</span><span style='color:#bb7722;'>d</span><span
                    style='color:#aa5511;'>r</span><span style='color:#884411;'>a</span><span
                    style='color:#663300;'>l</span></a></td>
        <td>12</td>
        <td>8445.253</td>
        <td>282.833</td>
    </tr>
    <tr>
        <td>459</td>
        <td><a href=players.php?pid=66251&edition=5>Suzuha._.</a></td>
        <td>12</td>
        <td>8446.653</td>
        <td>291.583</td>
    </tr>
    <tr>
        <td>460</td>
        <td><a href=players.php?pid=35123&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;iJaYzZx</span></a></td>
        <td>12</td>
        <td>8447.547</td>
        <td>297.167</td>
    </tr>
    <tr>
        <td>461</td>
        <td><a href=players.php?pid=1328&edition=5>NablaTM</a></td>
        <td>12</td>
        <td>8451.080</td>
        <td>319.250</td>
    </tr>
    <tr>
        <td>462</td>
        <td><a href=players.php?pid=40738&edition=5><span style='color:#ff66bb;'>CIOLA&nbsp;|&nbsp;Doc</span></a></td>
        <td>12</td>
        <td>8451.547</td>
        <td>322.167</td>
    </tr>
    <tr>
        <td>463</td>
        <td><a href=players.php?pid=22514&edition=5><span style='color:#000000;'>「</span><span
                    style='color:#ffffcc;'>B</span><span style='color:#eeeecc;'>&Delta;</span><span
                    style='color:#eecccc;'>B</span><span style='color:#ddbbcc;'>B</span><span
                    style='color:#cc99cc;'>Ə</span><span style='color:#000000;'>」</span></a></td>
        <td>12</td>
        <td>8451.827</td>
        <td>323.917</td>
    </tr>
    <tr>
        <td>464</td>
        <td><a href=players.php?pid=28493&edition=5>silk.TM</a></td>
        <td>12</td>
        <td>8453.107</td>
        <td>331.917</td>
    </tr>
    <tr>
        <td>465</td>
        <td><a href=players.php?pid=42991&edition=5>jxsh&nbsp;:smirkcat:</a></td>
        <td>12</td>
        <td>8453.973</td>
        <td>337.333</td>
    </tr>
    <tr>
        <td>466</td>
        <td><a href=players.php?pid=51737&edition=5><span style='color:#ff0000;font-weight:bold;'>Razz</span><span
                    style='color:#bb00ee;font-weight:bold;'>r</span></a></td>
        <td>12</td>
        <td>8454.093</td>
        <td>338.083</td>
    </tr>
    <tr>
        <td>467</td>
        <td><a href=players.php?pid=61564&edition=5>IIHollyII</a></td>
        <td>12</td>
        <td>8455.213</td>
        <td>345.083</td>
    </tr>
    <tr>
        <td>468</td>
        <td><a href=players.php?pid=44153&edition=5><span style='color:#ddcc55;'></span><span
                    style='color:#000000;'>↳</span><span style='color:#ffffff;'>tripnote</span></a></td>
        <td>12</td>
        <td>8455.307</td>
        <td>345.667</td>
    </tr>
    <tr>
        <td>469</td>
        <td><a href=players.php?pid=4888&edition=5><span style='color:#ee4444;'>D</span><span
                    style='color:#aa77cc;'>u</span><span style='color:#5599cc;'>dd</span><span
                    style='color:#55aadd;'>3l</span></a></td>
        <td>12</td>
        <td>8456.547</td>
        <td>353.417</td>
    </tr>
    <tr>
        <td>470</td>
        <td><a href=players.php?pid=10628&edition=5><span style='color:#ffffff;'>Power'.</span><span
                    style='color:#ccccff;'>K</span><span style='color:#ccccff;'>a</span><span
                    style='color:#bbbbff;'>c</span><span style='color:#bb99ff;'>c</span><span
                    style='color:#aa88ff;'>h</span><span style='color:#9966ff;'>i</span></a></td>
        <td>12</td>
        <td>8458.507</td>
        <td>365.667</td>
    </tr>
    <tr>
        <td>471</td>
        <td><a href=players.php?pid=1925&edition=5><span style='color:#0000cc;font-weight:bold;'>H</span><span
                    style='color:#0022cc;font-weight:bold;'>e</span><span
                    style='color:#0044dd;font-weight:bold;'>n</span><span
                    style='color:#0066dd;font-weight:bold;'>r</span><span
                    style='color:#0099ee;font-weight:bold;'>i</span><span
                    style='color:#00bbee;font-weight:bold;'>9</span><span
                    style='color:#00ddff;font-weight:bold;'>7</span><span
                    style='color:#00ffff;font-weight:bold;'>_</span></a></td>
        <td>12</td>
        <td>8458.600</td>
        <td>366.250</td>
    </tr>
    <tr>
        <td>472</td>
        <td><a href=players.php?pid=25203&edition=5><span style='color:#0088ff;'>MrFunnyFun</span></a></td>
        <td>12</td>
        <td>8460.560</td>
        <td>378.500</td>
    </tr>
    <tr>
        <td>473</td>
        <td><a href=players.php?pid=27922&edition=5><span style='color:#ff0000;'>!sl</span><span
                    style='color:#ff0000;'>ap&nbsp;</span><span style='color:#ffffff;'>ever</span><span
                    style='color:#ffffff;'>yone</span></a></td>
        <td>12</td>
        <td>8461.067</td>
        <td>381.667</td>
    </tr>
    <tr>
        <td>474</td>
        <td><a href=players.php?pid=59303&edition=5><span style='color:#ff44dd;font-weight:bold;'>T</span><span
                    style='color:#ff55dd;font-weight:bold;'>h</span><span
                    style='color:#ff66dd;font-weight:bold;'>e</span><span
                    style='color:#ff77dd;font-weight:bold;'>J</span><span
                    style='color:#ff88dd;font-weight:bold;'>a</span><span
                    style='color:#ff99dd;font-weight:bold;'>Z</span><span
                    style='color:#ffaadd;font-weight:bold;'>e</span><span
                    style='color:#ffbbdd;font-weight:bold;'>d</span></a></td>
        <td>12</td>
        <td>8462.093</td>
        <td>388.083</td>
    </tr>
    <tr>
        <td>475</td>
        <td><a href=players.php?pid=66290&edition=5><span style='color:#000000;'>F</span><span
                    style='color:#ffbb00;'>ox</span><span style='color:#000000;'>F</span><span
                    style='color:#ffbb00;'>ace</span><span style='color:#ffffff;'>TM</span></a></td>
        <td>12</td>
        <td>8463.013</td>
        <td>393.833</td>
    </tr>
    <tr>
        <td>476</td>
        <td><a href=players.php?pid=67198&edition=5>maBTM</a></td>
        <td>12</td>
        <td>8463.027</td>
        <td>393.917</td>
    </tr>
    <tr>
        <td>477</td>
        <td><a href=players.php?pid=32556&edition=5>:ben:</a></td>
        <td>12</td>
        <td>8464.627</td>
        <td>403.917</td>
    </tr>
    <tr>
        <td>478</td>
        <td><a href=players.php?pid=37570&edition=5>ProTrashCann</a></td>
        <td>12</td>
        <td>8465.773</td>
        <td>411.083</td>
    </tr>
    <tr>
        <td>479</td>
        <td><a href=players.php?pid=6587&edition=5><span style='color:#ffcc00;'>Jane</span><span
                    style='color:#aa8800;'>t</span><span style='color:#665511;'>J</span><span
                    style='color:#111111;'>nt</span></a></td>
        <td>12</td>
        <td>8466.173</td>
        <td>413.583</td>
    </tr>
    <tr>
        <td>480</td>
        <td><a href=players.php?pid=20839&edition=5>TD0g4002</a></td>
        <td>12</td>
        <td>8466.253</td>
        <td>414.083</td>
    </tr>
    <tr>
        <td>481</td>
        <td><a href=players.php?pid=52037&edition=5>darkov-</a></td>
        <td>12</td>
        <td>8466.693</td>
        <td>416.833</td>
    </tr>
    <tr>
        <td>482</td>
        <td><a href=players.php?pid=11712&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;TreborKaa</span></a></td>
        <td>12</td>
        <td>8466.960</td>
        <td>418.500</td>
    </tr>
    <tr>
        <td>483</td>
        <td><a href=players.php?pid=75&edition=5>BlackiTM</a></td>
        <td>12</td>
        <td>8467.347</td>
        <td>420.917</td>
    </tr>
    <tr>
        <td>484</td>
        <td><a href=players.php?pid=6313&edition=5>Xetarz</a></td>
        <td>12</td>
        <td>8467.573</td>
        <td>422.333</td>
    </tr>
    <tr>
        <td>485</td>
        <td><a href=players.php?pid=7479&edition=5><span style='color:#33ffff;'>C</span><span
                    style='color:#22ffcc;'>o</span><span style='color:#00ff99;'>p</span><span
                    style='color:#00ff99;'>C</span><span style='color:#00ff66;'>a</span><span
                    style='color:#00ff33;'>t</span></a></td>
        <td>12</td>
        <td>8468.333</td>
        <td>427.083</td>
    </tr>
    <tr>
        <td>486</td>
        <td><a href=players.php?pid=34190&edition=5>Aatholin</a></td>
        <td>12</td>
        <td>8468.400</td>
        <td>427.500</td>
    </tr>
    <tr>
        <td>487</td>
        <td><a href=players.php?pid=20381&edition=5><span style='color:#ff9900;'>D.i.o.</span><span
                    style='color:#ffffff;'>x.a.s.</span></a></td>
        <td>12</td>
        <td>8468.693</td>
        <td>429.333</td>
    </tr>
    <tr>
        <td>488</td>
        <td><a href=players.php?pid=8536&edition=5><span style='color:#0000cc;'>Ł</span><span
                    style='color:#0011dd;'>&sigma;</span><span style='color:#0022dd;'>&alpha;</span><span
                    style='color:#0033ee;'>ȡ</span><span style='color:#0044ee;'>ϊ</span><span
                    style='color:#0055ff;'>ก</span><span style='color:#0066ff;'>ǥ&nbsp;</span><span
                    style='color:#66ffff;'>々&nbsp;</span><span style='color:#000000;'>&not;&nbsp;AckSter</span></a></td>
        <td>12</td>
        <td>8472.107</td>
        <td>450.667</td>
    </tr>
    <tr>
        <td>489</td>
        <td><a href=players.php?pid=49289&edition=5>NengZwee</a></td>
        <td>12</td>
        <td>8473.680</td>
        <td>460.500</td>
    </tr>
    <tr>
        <td>490</td>
        <td><a href=players.php?pid=9122&edition=5>Լ:owo::e:Ϯΐϝ&alpha;&pi;Ϯ</a></td>
        <td>12</td>
        <td>8474.573</td>
        <td>466.083</td>
    </tr>
    <tr>
        <td>491</td>
        <td><a href=players.php?pid=68793&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Le_co_que</span></a></td>
        <td>12</td>
        <td>8476.933</td>
        <td>480.833</td>
    </tr>
    <tr>
        <td>492</td>
        <td><a href=players.php?pid=29389&edition=5><span style='color:#000099;'>P</span><span
                    style='color:#0022aa;'>e</span><span style='color:#0033aa;'>n</span><span
                    style='color:#0055bb;'>g</span><span style='color:#0077cc;'>u</span><span
                    style='color:#0088cc;'>i</span><span style='color:#00aadd;'>n</span><span
                    style='color:#00ccee;'>.</span><span style='color:#00ddee;'>T</span><span
                    style='color:#00ffff;'>M</span></a></td>
        <td>12</td>
        <td>8477.080</td>
        <td>481.750</td>
    </tr>
    <tr>
        <td>493</td>
        <td><a href=players.php?pid=6767&edition=5><span style='color:#999999;'>の</span><span
                    style='color:#998888;'>i</span><span style='color:#887766;'>g</span><span
                    style='color:#886655;'>巳</span><span style='color:#776644;'>a</span><span
                    style='color:#775533;'>r</span><span style='color:#664411;'>t</span><span
                    style='color:#663300;'>h</span></a></td>
        <td>12</td>
        <td>8477.867</td>
        <td>486.667</td>
    </tr>
    <tr>
        <td>494</td>
        <td><a href=players.php?pid=13269&edition=5>NOR-_-Bacon3</a></td>
        <td>12</td>
        <td>8478.360</td>
        <td>489.750</td>
    </tr>
    <tr>
        <td>495</td>
        <td><a href=players.php?pid=68176&edition=5>lotus</a></td>
        <td>12</td>
        <td>8481.347</td>
        <td>508.417</td>
    </tr>
    <tr>
        <td>496</td>
        <td><a href=players.php?pid=34879&edition=5>MSA_111</a></td>
        <td>12</td>
        <td>8486.893</td>
        <td>543.083</td>
    </tr>
    <tr>
        <td>497</td>
        <td><a href=players.php?pid=6813&edition=5>th0rn3d</a></td>
        <td>12</td>
        <td>8490.827</td>
        <td>567.667</td>
    </tr>
    <tr>
        <td>498</td>
        <td><a href=players.php?pid=66252&edition=5>jac0b97</a></td>
        <td>12</td>
        <td>8495.387</td>
        <td>596.167</td>
    </tr>
    <tr>
        <td>499</td>
        <td><a href=players.php?pid=30228&edition=5>melchenko123</a></td>
        <td>12</td>
        <td>8496.280</td>
        <td>601.750</td>
    </tr>
    <tr>
        <td>500</td>
        <td><a href=players.php?pid=1279&edition=5><span style='color:#9933ff;'>M</span><span
                    style='color:#aa55dd;'>r</span><span style='color:#bb66bb;'>R</span><span
                    style='color:#cc8899;'>i</span><span style='color:#ccaa66;'>c</span><span
                    style='color:#ddcc44;'>k</span><span style='color:#eedd22;'>4</span><span
                    style='color:#ffff00;'>1</span></a></td>
        <td>11</td>
        <td>8560.120</td>
        <td>182.636</td>
    </tr>
    <tr>
        <td>501</td>
        <td><a href=players.php?pid=66802&edition=5><span style='color:#9900ff;'>D</span><span
                    style='color:#bb00ff;'>o</span><span style='color:#dd00ff;'>s</span><span
                    style='color:#dd00ff;'>l</span><span style='color:#ee00ff;'>yd</span><span
                    style='color:#ff00ff;'>oo</span></a></td>
        <td>11</td>
        <td>8560.853</td>
        <td>187.636</td>
    </tr>
    <tr>
        <td>502</td>
        <td><a href=players.php?pid=33168&edition=5><span style='color:#0033ff;'>H</span><span
                    style='color:#2299ff;'>o</span><span style='color:#33ffff;'>v</span><span
                    style='color:#33ffff;'>e</span><span style='color:#33ff88;'>T</span><span
                    style='color:#33ff00;'>M</span></a></td>
        <td>11</td>
        <td>8572.427</td>
        <td>266.545</td>
    </tr>
    <tr>
        <td>503</td>
        <td><a href=players.php?pid=32238&edition=5><span style='color:#000000;font-weight:bold;'>fake&nbsp;</span><span
                    style='color:#55bbaa;letter-spacing: -0.1em;font-size:smaller'>YOU</span><span
                    style='color:#228888;letter-spacing: -0.1em;font-size:smaller'>MOL</span></a></td>
        <td>11</td>
        <td>8576.213</td>
        <td>292.364</td>
    </tr>
    <tr>
        <td>504</td>
        <td><a href=players.php?pid=8676&edition=5>CormacDomain</a></td>
        <td>11</td>
        <td>8576.227</td>
        <td>292.455</td>
    </tr>
    <tr>
        <td>505</td>
        <td><a href=players.php?pid=65208&edition=5><span style='color:#663399;'>Jona</span><span
                    style='color:#006699;'>Mat</span><span style='color:#66ffff;'>Goo</span></a></td>
        <td>11</td>
        <td>8577.413</td>
        <td>300.545</td>
    </tr>
    <tr>
        <td>506</td>
        <td><a href=players.php?pid=28597&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='font-style:italic;'>&nbsp;Senkey15&nbsp;</span></a></td>
        <td>11</td>
        <td>8580.787</td>
        <td>323.545</td>
    </tr>
    <tr>
        <td>507</td>
        <td><a href=players.php?pid=36757&edition=5>Dada6_coasters</a></td>
        <td>11</td>
        <td>8581.613</td>
        <td>329.182</td>
    </tr>
    <tr>
        <td>508</td>
        <td><a href=players.php?pid=9275&edition=5>ObiyoTM</a></td>
        <td>11</td>
        <td>8582.147</td>
        <td>332.818</td>
    </tr>
    <tr>
        <td>509</td>
        <td><a href=players.php?pid=65568&edition=5>exix_77</a></td>
        <td>11</td>
        <td>8583.733</td>
        <td>343.636</td>
    </tr>
    <tr>
        <td>510</td>
        <td><a href=players.php?pid=20971&edition=5><span style='color:#ee2233;'>&Ccedil;</span><span
                    style='color:#cc2266;font-style:italic;font-weight:bold;'>y</span><span
                    style='color:#aa1199;font-style:italic;font-weight:bold;'>b</span><span
                    style='color:#8811cc;font-style:italic;font-weight:bold;'>e</span><span
                    style='color:#5500ff;font-style:italic;font-weight:bold;'>r</span></a></td>
        <td>11</td>
        <td>8583.827</td>
        <td>344.273</td>
    </tr>
    <tr>
        <td>511</td>
        <td><a href=players.php?pid=70301&edition=5>madeice</a></td>
        <td>11</td>
        <td>8584.120</td>
        <td>346.273</td>
    </tr>
    <tr>
        <td>512</td>
        <td><a href=players.php?pid=67058&edition=5><span style='color:#99ffff;font-style:italic;'>tr</span><span
                    style='color:#66ffff;font-style:italic;'>ee</span><span
                    style='color:#33ffff;font-style:italic;'>-</span><span
                    style='color:#00ffff;font-style:italic;'>tm</span></a></td>
        <td>11</td>
        <td>8585.400</td>
        <td>355.000</td>
    </tr>
    <tr>
        <td>513</td>
        <td><a href=players.php?pid=67206&edition=5>Kick_Squirrel</a></td>
        <td>11</td>
        <td>8586.813</td>
        <td>364.636</td>
    </tr>
    <tr>
        <td>514</td>
        <td><a href=players.php?pid=11764&edition=5><span style='color:#ff0000;'>Ca</span><span
                    style='color:#dd1133;'>mo</span><span style='color:#bb1155;'>Br</span><span
                    style='color:#aa2288;'>ie</span><span style='color:#8833aa;'>&nbsp;</span><span
                    style='color:#7733bb;'>&laquo;</span><span style='color:#6633dd;'>&nbsp;</span><span
                    style='color:#5544ee;'>т&sup3;</span></a></td>
        <td>11</td>
        <td>8589.160</td>
        <td>380.636</td>
    </tr>
    <tr>
        <td>515</td>
        <td><a href=players.php?pid=66246&edition=5>pprraann</a></td>
        <td>11</td>
        <td>8590.533</td>
        <td>390.000</td>
    </tr>
    <tr>
        <td>516</td>
        <td><a href=players.php?pid=14626&edition=5>:ben:<span style='color:#ff0000;'>m</span><span
                    style='color:#ff8800;'>a</span><span style='color:#ffff00;'>n</span></a></td>
        <td>11</td>
        <td>8593.000</td>
        <td>406.818</td>
    </tr>
    <tr>
        <td>517</td>
        <td><a href=players.php?pid=69213&edition=5><span style='color:#ff66ff;'>Q</span><span
                    style='color:#ff66cc;'>C</span></a></td>
        <td>11</td>
        <td>8594.547</td>
        <td>417.364</td>
    </tr>
    <tr>
        <td>518</td>
        <td><a href=players.php?pid=135&edition=5><span style='color:#cccc00;'>M</span><span
                    style='color:#cccc22;'>a</span><span style='color:#dddd55;'>y</span><span
                    style='color:#dddd77;'>h</span><span style='color:#eeee99;'>m</span><span
                    style='color:#eeeebb;'>e</span><span style='color:#ffffdd;'>m</span><span
                    style='color:#ffffff;'>e</span></a></td>
        <td>11</td>
        <td>8594.933</td>
        <td>420.000</td>
    </tr>
    <tr>
        <td>519</td>
        <td><a href=players.php?pid=66393&edition=5><span style='color:#33ff00;'>Daniel</span><span
                    style='color:#ff66ff;'>Chips</span></a></td>
        <td>11</td>
        <td>8596.907</td>
        <td>433.455</td>
    </tr>
    <tr>
        <td>520</td>
        <td><a href=players.php?pid=28218&edition=5><span style='color:#ff66ff;'>R</span><span
                    style='color:#ff88ee;'>i</span><span style='color:#ff99ee;'>d</span><span
                    style='color:#ffbbdd;'>i</span><span style='color:#ffcccc;'>c</span><span
                    style='color:#ffcccc;'>u</span><span style='color:#ffaadd;'>l</span><span
                    style='color:#ff88ee;'>u</span><span style='color:#ff66ff;'>m</span></a></td>
        <td>11</td>
        <td>8597.560</td>
        <td>437.909</td>
    </tr>
    <tr>
        <td>521</td>
        <td><a href=players.php?pid=36929&edition=5>Woshus</a></td>
        <td>11</td>
        <td>8599.600</td>
        <td>451.818</td>
    </tr>
    <tr>
        <td>522</td>
        <td><a href=players.php?pid=32673&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='color:#550055;font-style:italic;'>Ha</span><span
                    style='color:#770077;font-style:italic;'>s</span><span
                    style='color:#990099;font-style:italic;'>h</span><span
                    style='color:#990099;font-style:italic;'>b</span><span
                    style='color:#aa00aa;font-style:italic;'>j</span><span
                    style='color:#880099;font-style:italic;'>&oslash;</span><span
                    style='color:#770088;font-style:italic;'>r</span><span
                    style='color:#660077;font-style:italic;'>n</span></a></td>
        <td>11</td>
        <td>8599.693</td>
        <td>452.455</td>
    </tr>
    <tr>
        <td>523</td>
        <td><a href=players.php?pid=7482&edition=5><span style='color:#0000cc;'>R</span><span
                    style='color:#4400bb;'>i</span><span style='color:#8800bb;'>c</span><span
                    style='color:#bb00aa;'>h</span><span style='color:#ff0099;'>_</span><span
                    style='color:#ff0099;'>T</span><span style='color:#aa0066;'>M</span><span
                    style='color:#550033;'>R</span><span style='color:#000000;'>L</span></a></td>
        <td>11</td>
        <td>8601.667</td>
        <td>465.909</td>
    </tr>
    <tr>
        <td>524</td>
        <td><a href=players.php?pid=14904&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Yoke</span></a></td>
        <td>11</td>
        <td>8601.920</td>
        <td>467.636</td>
    </tr>
    <tr>
        <td>525</td>
        <td><a href=players.php?pid=29357&edition=5>Steve.the.Bug.</a></td>
        <td>11</td>
        <td>8603.253</td>
        <td>476.727</td>
    </tr>
    <tr>
        <td>526</td>
        <td><a href=players.php?pid=66454&edition=5><span style='color:#00ffff;'>o</span><span
                    style='color:#00ddee;'>s</span><span style='color:#00ccdd;'>i</span><span
                    style='color:#00aadd;'>r</span><span style='color:#0088cc;'>i</span><span
                    style='color:#0077bb;'>s</span><span style='color:#0055aa;'>c</span><span
                    style='color:#0033aa;'>o</span><span style='color:#002299;'>r</span><span
                    style='color:#000088;'>p</span></a></td>
        <td>11</td>
        <td>8605.040</td>
        <td>488.909</td>
    </tr>
    <tr>
        <td>527</td>
        <td><a href=players.php?pid=15119&edition=5><span style='color:#ff00ff;'>n</span><span
                    style='color:#dd11ff;'>f</span><span style='color:#aa22ff;'>n</span><span
                    style='color:#8844ff;'>i</span><span style='color:#5555ff;'>t</span><span
                    style='color:#3366ff;'>e</span></a></td>
        <td>11</td>
        <td>8605.613</td>
        <td>492.818</td>
    </tr>
    <tr>
        <td>528</td>
        <td><a href=players.php?pid=17764&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>Proxx</span></a></td>
        <td>11</td>
        <td>8607.040</td>
        <td>502.545</td>
    </tr>
    <tr>
        <td>529</td>
        <td><a href=players.php?pid=9557&edition=5><span style='color:#ff3399;'>ā</span><span
                    style='color:#bb33aa;'>.</span><span style='color:#8833bb;'>&nbsp;</span><span
                    style='color:#4433bb;'>Ł</span><span style='color:#0033cc;'>モ</span><span
                    style='color:#0033cc;'>&nbsp;</span><span style='color:#0022dd;'>ģ</span><span
                    style='color:#0011ee;'>&oacute;</span><span style='color:#0000ff;'>D</span></a></td>
        <td>11</td>
        <td>8607.227</td>
        <td>503.818</td>
    </tr>
    <tr>
        <td>530</td>
        <td><a href=players.php?pid=51803&edition=5><span
                    style='color:#ff0000;font-style:italic;font-weight:bold;'>C</span><span
                    style='color:#ff2200;font-style:italic;font-weight:bold;'>a</span><span
                    style='color:#ff4400;font-style:italic;font-weight:bold;'>l</span><span
                    style='color:#ff5500;font-style:italic;font-weight:bold;'>l</span><span
                    style='color:#ff7700;font-style:italic;font-weight:bold;'>m</span><span
                    style='color:#ff9900;font-style:italic;font-weight:bold;'>e</span><span
                    style='color:#ff9900;font-style:italic;font-weight:bold;'>j</span><span
                    style='color:#ff7700;font-style:italic;font-weight:bold;'>o</span><span
                    style='color:#ff5500;font-style:italic;font-weight:bold;'>e</span><span
                    style='color:#ff2200;font-style:italic;font-weight:bold;'>r</span><span
                    style='color:#ff0000;font-style:italic;font-weight:bold;'>i</span></a></td>
        <td>11</td>
        <td>8608.427</td>
        <td>512.000</td>
    </tr>
    <tr>
        <td>531</td>
        <td><a href=players.php?pid=67369&edition=5>jmdragon370</a></td>
        <td>11</td>
        <td>8609.000</td>
        <td>515.909</td>
    </tr>
    <tr>
        <td>532</td>
        <td><a href=players.php?pid=52929&edition=5><span style='color:#cc6600;'>丁</span><span
                    style='color:#dd8844;'>u</span><span style='color:#ddaa77;'>a</span><span
                    style='color:#eeccbb;'>n</span><span style='color:#eeeeee;'>の</span><span
                    style='color:#eeeeee;'>o</span><span style='color:#eeccbb;'>r</span><span
                    style='color:#ddaa77;'>i</span><span style='color:#dd8844;'>a</span><span
                    style='color:#cc6600;'>n</span></a></td>
        <td>11</td>
        <td>8610.320</td>
        <td>524.909</td>
    </tr>
    <tr>
        <td>533</td>
        <td><a href=players.php?pid=37024&edition=5>wilderness14</a></td>
        <td>11</td>
        <td>8610.973</td>
        <td>529.364</td>
    </tr>
    <tr>
        <td>534</td>
        <td><a href=players.php?pid=55379&edition=5>Semsen2604</a></td>
        <td>11</td>
        <td>8612.987</td>
        <td>543.091</td>
    </tr>
    <tr>
        <td>535</td>
        <td><a href=players.php?pid=20958&edition=5><span style='color:#0000cc;font-weight:bold;'>V</span><span
                    style='color:#0022cc;font-weight:bold;'>e</span><span
                    style='color:#1144dd;font-weight:bold;'>r</span><span
                    style='color:#1166dd;font-weight:bold;'>i</span><span
                    style='color:#2299ee;font-weight:bold;'>e</span><span
                    style='color:#22bbee;font-weight:bold;'>_</span><span
                    style='color:#33ddff;font-weight:bold;'>g</span><span
                    style='color:#33ffff;font-weight:bold;'>o</span><span
                    style='color:#33ffff;font-weight:bold;'>o</span><span
                    style='color:#33ddff;font-weight:bold;'>d</span><span
                    style='color:#22bbee;font-weight:bold;'>e</span><span
                    style='color:#2299ee;font-weight:bold;'>_</span><span
                    style='color:#1166dd;font-weight:bold;'>n</span><span
                    style='color:#1144dd;font-weight:bold;'>a</span><span
                    style='color:#0022cc;font-weight:bold;'>a</span><span
                    style='color:#0000cc;font-weight:bold;'>m</span></a></td>
        <td>11</td>
        <td>8613.040</td>
        <td>543.455</td>
    </tr>
    <tr>
        <td>536</td>
        <td><a href=players.php?pid=40253&edition=5>Rtaliesin</a></td>
        <td>11</td>
        <td>8613.173</td>
        <td>544.364</td>
    </tr>
    <tr>
        <td>537</td>
        <td><a href=players.php?pid=6814&edition=5><span style='color:#ffcc00;'>G</span><span
                    style='color:#ffffff;'>lider</span><span style='color:#ffcc00;'>H</span><span
                    style='color:#ffffff;'>ater</span></a></td>
        <td>11</td>
        <td>8614.840</td>
        <td>555.727</td>
    </tr>
    <tr>
        <td>538</td>
        <td><a href=players.php?pid=68594&edition=5><span style='color:#000000;'>ad</span><span
                    style='color:#ff0000;'>1</span><span style='color:#000000;'>qua</span></a></td>
        <td>11</td>
        <td>8614.933</td>
        <td>556.364</td>
    </tr>
    <tr>
        <td>539</td>
        <td><a href=players.php?pid=10399&edition=5>The.red24</a></td>
        <td>11</td>
        <td>8616.347</td>
        <td>566.000</td>
    </tr>
    <tr>
        <td>540</td>
        <td><a href=players.php?pid=52024&edition=5>A------------ar</a></td>
        <td>10</td>
        <td>8683.133</td>
        <td>123.500</td>
    </tr>
    <tr>
        <td>541</td>
        <td><a href=players.php?pid=6212&edition=5><span style='color:#ffff00;'>marmerladi</span></a></td>
        <td>10</td>
        <td>8689.107</td>
        <td>168.300</td>
    </tr>
    <tr>
        <td>542</td>
        <td><a href=players.php?pid=55144&edition=5>banthediabetics</a></td>
        <td>10</td>
        <td>8700.667</td>
        <td>255.000</td>
    </tr>
    <tr>
        <td>543</td>
        <td><a href=players.php?pid=20424&edition=5><span style='color:#774400;'>ž</span><span
                    style='color:#775522;'>ё</span><span style='color:#665544;'>Ҟ</span><span
                    style='color:#666666;'>ע</span></a></td>
        <td>10</td>
        <td>8701.467</td>
        <td>261.000</td>
    </tr>
    <tr>
        <td>544</td>
        <td><a href=players.php?pid=26249&edition=5>xHonzaizX</a></td>
        <td>10</td>
        <td>8701.747</td>
        <td>263.100</td>
    </tr>
    <tr>
        <td>545</td>
        <td><a href=players.php?pid=11681&edition=5><span style='color:#0000ff;'>sp</span><span
                    style='color:#ffffff;'>eny</span><span style='color:#0000ff;'>37</span></a></td>
        <td>10</td>
        <td>8702.360</td>
        <td>267.700</td>
    </tr>
    <tr>
        <td>546</td>
        <td><a href=players.php?pid=1235&edition=5>[0]&nbsp;Radiance</a></td>
        <td>10</td>
        <td>8704.213</td>
        <td>281.600</td>
    </tr>
    <tr>
        <td>547</td>
        <td><a href=players.php?pid=64858&edition=5>zIxWHITExIz</a></td>
        <td>10</td>
        <td>8705.480</td>
        <td>291.100</td>
    </tr>
    <tr>
        <td>548</td>
        <td><a href=players.php?pid=49116&edition=5><span style='color:#33aa55;'>&nbsp;שｪה</span><span
                    style='color:#ffffff;'>Đőผ&scaron;&nbsp;&nbsp;</span><span style='color:#33aa55;'>ҳ</span><span
                    style='color:#ffffff;'>ｬ</span></a></td>
        <td>10</td>
        <td>8705.920</td>
        <td>294.400</td>
    </tr>
    <tr>
        <td>549</td>
        <td><a href=players.php?pid=66189&edition=5>baxteri</a></td>
        <td>10</td>
        <td>8708.467</td>
        <td>313.500</td>
    </tr>
    <tr>
        <td>550</td>
        <td><a href=players.php?pid=43776&edition=5>Shxy_an</a></td>
        <td>10</td>
        <td>8709.400</td>
        <td>320.500</td>
    </tr>
    <tr>
        <td>551</td>
        <td><a href=players.php?pid=52358&edition=5>kippys</a></td>
        <td>10</td>
        <td>8709.413</td>
        <td>320.600</td>
    </tr>
    <tr>
        <td>552</td>
        <td><a href=players.php?pid=6743&edition=5><span style='color:#000000;'>B</span><span
                    style='color:#550000;'>l</span><span style='color:#aa0000;'>o</span><span
                    style='color:#ff0000;'>o</span><span style='color:#ff0000;'>d</span><span
                    style='color:#880000;'>ツ</span><span style='color:#000000;'>&nbsp;</span></a></td>
        <td>10</td>
        <td>8709.493</td>
        <td>321.200</td>
    </tr>
    <tr>
        <td>553</td>
        <td><a href=players.php?pid=41854&edition=5>BottomFragger55</a></td>
        <td>10</td>
        <td>8709.627</td>
        <td>322.200</td>
    </tr>
    <tr>
        <td>554</td>
        <td><a href=players.php?pid=7061&edition=5>Kyumitsu</a></td>
        <td>10</td>
        <td>8710.213</td>
        <td>326.600</td>
    </tr>
    <tr>
        <td>555</td>
        <td><a href=players.php?pid=65264&edition=5>VictorPro123YT</a></td>
        <td>10</td>
        <td>8711.040</td>
        <td>332.800</td>
    </tr>
    <tr>
        <td>556</td>
        <td><a href=players.php?pid=49698&edition=5>s:owo:nity</a></td>
        <td>10</td>
        <td>8712.840</td>
        <td>346.300</td>
    </tr>
    <tr>
        <td>557</td>
        <td><a href=players.php?pid=15071&edition=5>Hshsdes2</a></td>
        <td>10</td>
        <td>8712.947</td>
        <td>347.100</td>
    </tr>
    <tr>
        <td>558</td>
        <td><a href=players.php?pid=11129&edition=5><span style='color:#000000;'>j</span><span
                    style='color:#000011;'>a</span><span style='color:#000022;'>a</span><span
                    style='color:#000044;'>a</span><span style='color:#000055;'>a</span><span
                    style='color:#000066;'>n</span></a></td>
        <td>10</td>
        <td>8713.613</td>
        <td>352.100</td>
    </tr>
    <tr>
        <td>559</td>
        <td><a href=players.php?pid=7734&edition=5>gavindejong</a></td>
        <td>10</td>
        <td>8714.200</td>
        <td>356.500</td>
    </tr>
    <tr>
        <td>560</td>
        <td><a href=players.php?pid=67715&edition=5>Tipiiiizor</a></td>
        <td>10</td>
        <td>8715.067</td>
        <td>363.000</td>
    </tr>
    <tr>
        <td>561</td>
        <td><a href=players.php?pid=71137&edition=5>bread</a></td>
        <td>10</td>
        <td>8716.613</td>
        <td>374.600</td>
    </tr>
    <tr>
        <td>562</td>
        <td><a href=players.php?pid=35218&edition=5><span style='color:#00ff66;'>〒</span><span
                    style='color:#00ee88;'>ą</span><span style='color:#00eebb;'>г</span><span
                    style='color:#00dddd;'>ҡ</span><span style='color:#00ccff;'>丫</span></a></td>
        <td>10</td>
        <td>8717.053</td>
        <td>377.900</td>
    </tr>
    <tr>
        <td>563</td>
        <td><a href=players.php?pid=43582&edition=5>rbseattle</a></td>
        <td>10</td>
        <td>8717.360</td>
        <td>380.200</td>
    </tr>
    <tr>
        <td>564</td>
        <td><a href=players.php?pid=67429&edition=5>petitbetit</a></td>
        <td>10</td>
        <td>8718.240</td>
        <td>386.800</td>
    </tr>
    <tr>
        <td>565</td>
        <td><a href=players.php?pid=66919&edition=5><span style='color:#ffff66;'>M</span><span
                    style='color:#ddff99;'>a</span><span style='color:#bbffcc;'>v</span><span
                    style='color:#99ffff;'>u</span><span style='color:#99ffff;'>i</span><span
                    style='color:#cceeaa;'>k</span><span style='color:#ffcc55;'>a</span></a></td>
        <td>10</td>
        <td>8719.067</td>
        <td>393.000</td>
    </tr>
    <tr>
        <td>566</td>
        <td><a href=players.php?pid=63629&edition=5><span style='color:#88bbcc;'>永&nbsp;</span><span
                    style='color:#ccffff;'>Ja</span><span style='color:#bbffff;'>gl</span><span
                    style='color:#aaffff;'>a</span><span style='color:#99ffff;'>no</span></a></td>
        <td>10</td>
        <td>8719.133</td>
        <td>393.500</td>
    </tr>
    <tr>
        <td>567</td>
        <td><a href=players.php?pid=4&edition=5><span style='color:#00ff00;font-weight:bold;'>ins</span></a></td>
        <td>10</td>
        <td>8719.347</td>
        <td>395.100</td>
    </tr>
    <tr>
        <td>568</td>
        <td><a href=players.php?pid=22869&edition=5>nellike</a></td>
        <td>10</td>
        <td>8720.200</td>
        <td>401.500</td>
    </tr>
    <tr>
        <td>569</td>
        <td><a href=players.php?pid=69598&edition=5>gudevides</a></td>
        <td>10</td>
        <td>8720.453</td>
        <td>403.400</td>
    </tr>
    <tr>
        <td>570</td>
        <td><a href=players.php?pid=26478&edition=5><span style='color:#1188aa;'>Ɖ</span><span
                    style='color:#ffffff;'>inoo</span><span style='color:#1188aa;'>ƃ</span></a></td>
        <td>10</td>
        <td>8722.160</td>
        <td>416.200</td>
    </tr>
    <tr>
        <td>571</td>
        <td><a href=players.php?pid=6156&edition=5><span style='color:#aaaa33;'>G</span><span
                    style='color:#bbbb33;'>o</span><span style='color:#bbcc22;'>d</span><span
                    style='color:#cccc22;'>s</span><span style='color:#ccdd22;'>L</span><span
                    style='color:#ccdd11;'>o</span><span style='color:#ddee11;'>y</span><span
                    style='color:#ddee00;'>a</span><span style='color:#eeff00;'>l</span></a></td>
        <td>10</td>
        <td>8722.907</td>
        <td>421.800</td>
    </tr>
    <tr>
        <td>572</td>
        <td><a href=players.php?pid=39270&edition=5>RostiljMajstor</a></td>
        <td>10</td>
        <td>8723.227</td>
        <td>424.200</td>
    </tr>
    <tr>
        <td>573</td>
        <td><a href=players.php?pid=8303&edition=5>EpiDemic4</a></td>
        <td>10</td>
        <td>8723.773</td>
        <td>428.300</td>
    </tr>
    <tr>
        <td>574</td>
        <td><a href=players.php?pid=24911&edition=5><span style='color:#000000;'>G</span><span
                    style='color:#335555;'>r</span><span style='color:#66aaaa;'>a</span><span
                    style='color:#99ffff;'>v</span><span style='color:#99ffff;'>i</span><span
                    style='color:#bbffff;'>t</span><span style='color:#ddffff;'>y</span><span
                    style='color:#ffffff;'>.Mobbi</span></a></td>
        <td>10</td>
        <td>8724.040</td>
        <td>430.300</td>
    </tr>
    <tr>
        <td>575</td>
        <td><a href=players.php?pid=7495&edition=5>Santav55</a></td>
        <td>10</td>
        <td>8724.173</td>
        <td>431.300</td>
    </tr>
    <tr>
        <td>576</td>
        <td><a href=players.php?pid=64783&edition=5>Slash.TM</a></td>
        <td>10</td>
        <td>8724.387</td>
        <td>432.900</td>
    </tr>
    <tr>
        <td>577</td>
        <td><a href=players.php?pid=28448&edition=5><span
                    style='color:#9966ff;letter-spacing: -0.1em;font-size:smaller'>zybbbbbbbb</span></a></td>
        <td>10</td>
        <td>8724.827</td>
        <td>436.200</td>
    </tr>
    <tr>
        <td>578</td>
        <td><a href=players.php?pid=12374&edition=5><span
                    style='color:#ff6633;letter-spacing: -0.1em;font-size:smaller'>M</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>U</span><span
                    style='color:#ff6633;letter-spacing: -0.1em;font-size:smaller'>S</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>T</span><span
                    style='color:#ff6633;letter-spacing: -0.1em;font-size:smaller'>A</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>R</span><span
                    style='color:#ff6633;letter-spacing: -0.1em;font-size:smaller'>D</span></a></td>
        <td>10</td>
        <td>8724.880</td>
        <td>436.600</td>
    </tr>
    <tr>
        <td>579</td>
        <td><a href=players.php?pid=28715&edition=5><span style='color:#cc00ff;'>E</span><span
                    style='color:#aa55ff;'>d</span><span style='color:#88aaff;'>e</span><span
                    style='color:#66ffff;'>n</span></a></td>
        <td>10</td>
        <td>8725.867</td>
        <td>444.000</td>
    </tr>
    <tr>
        <td>580</td>
        <td><a href=players.php?pid=31831&edition=5><span style='color:#550099;'>E</span><span
                    style='color:#6600bb;'>d</span><span style='color:#7700cc;'>i</span><span
                    style='color:#8800ee;'>m</span><span style='color:#9900ff;'>a</span><span
                    style='color:#aa22ff;'>l</span><span style='color:#aa33ff;'>o</span><span
                    style='color:#bb55ff;'>u</span><span style='color:#bb66ff;'></span></a></td>
        <td>10</td>
        <td>8727.627</td>
        <td>457.200</td>
    </tr>
    <tr>
        <td>581</td>
        <td><a href=players.php?pid=46817&edition=5>N0<span style='color:#ffffff;'>xie</span></a></td>
        <td>10</td>
        <td>8727.907</td>
        <td>459.300</td>
    </tr>
    <tr>
        <td>582</td>
        <td><a href=players.php?pid=51741&edition=5>HazieMoo</a></td>
        <td>10</td>
        <td>8728.240</td>
        <td>461.800</td>
    </tr>
    <tr>
        <td>583</td>
        <td><a href=players.php?pid=59669&edition=5><span style='color:#77cc44;'>R</span><span
                    style='color:#ffcccc;'>i</span><span style='color:#ffcccc;'>i</span><span
                    style='color:#bb88aa;'>z</span><span style='color:#773399;'>k</span></a></td>
        <td>10</td>
        <td>8728.280</td>
        <td>462.100</td>
    </tr>
    <tr>
        <td>584</td>
        <td><a href=players.php?pid=16238&edition=5><span style='color:#eeffff;'>l</span><span
                    style='color:#ddeedd;'>e</span><span style='color:#bbeebb;'>r</span><span
                    style='color:#aadd99;'>m</span><span style='color:#99cc88;'>a</span><span
                    style='color:#77bb66;'>n</span><span style='color:#66bb44;'>d</span>0<span
                    style='color:#339900;'>7</span></a></td>
        <td>10</td>
        <td>8729.347</td>
        <td>470.100</td>
    </tr>
    <tr>
        <td>585</td>
        <td><a href=players.php?pid=2466&edition=5>Eria-.</a></td>
        <td>10</td>
        <td>8731.933</td>
        <td>489.500</td>
    </tr>
    <tr>
        <td>586</td>
        <td><a href=players.php?pid=53427&edition=5>knackstift</a></td>
        <td>10</td>
        <td>8733.387</td>
        <td>500.400</td>
    </tr>
    <tr>
        <td>587</td>
        <td><a href=players.php?pid=39562&edition=5>WavByBy</a></td>
        <td>10</td>
        <td>8733.733</td>
        <td>503.000</td>
    </tr>
    <tr>
        <td>588</td>
        <td><a href=players.php?pid=47516&edition=5><span style='color:#4400aa;'>Pu</span><span
                    style='color:#3311aa;'>rp</span><span style='color:#221199;'>le&nbsp;</span><span
                    style='color:#002288;'>Du</span><span style='color:#003388;'>o-</span><span
                    style='color:#4400aa;'>na</span><span style='color:#661199;'>ts</span><span
                    style='color:#882288;'>uc</span><span style='color:#aa2277;'>an</span><span
                    style='color:#cc3366;'>ta</span><span style='color:#ee4455;'>i</span><span
                    style='color:#ff5555;'>m</span><span style='color:#6644aa;'></span></a></td>
        <td>10</td>
        <td>8734.173</td>
        <td>506.300</td>
    </tr>
    <tr>
        <td>589</td>
        <td><a href=players.php?pid=64393&edition=5>GregTheRabbi</a></td>
        <td>10</td>
        <td>8734.987</td>
        <td>512.400</td>
    </tr>
    <tr>
        <td>590</td>
        <td><a href=players.php?pid=6235&edition=5><span style='color:#000000;'>JJG-</span></a></td>
        <td>10</td>
        <td>8735.360</td>
        <td>515.200</td>
    </tr>
    <tr>
        <td>591</td>
        <td><a href=players.php?pid=18207&edition=5><span style='color:#0000ff;font-weight:bold;'>FORTNITE</span><span
                    style='color:#ffffff;font-weight:bold;'>BALLS</span></a></td>
        <td>10</td>
        <td>8735.680</td>
        <td>517.600</td>
    </tr>
    <tr>
        <td>592</td>
        <td><a href=players.php?pid=8415&edition=5><span style='font-weight:bold;'>&nbsp;NAUU</span></a></td>
        <td>10</td>
        <td>8735.840</td>
        <td>518.800</td>
    </tr>
    <tr>
        <td>593</td>
        <td><a href=players.php?pid=10812&edition=5><span style='color:#66ff33;font-weight:bold;'>R</span><span
                    style='color:#88ff33;font-weight:bold;'>a</span><span
                    style='color:#99ff22;font-weight:bold;'>s</span><span
                    style='color:#bbff22;font-weight:bold;'>t</span><span
                    style='color:#ccff11;font-weight:bold;'>a</span><span
                    style='color:#eeff11;font-weight:bold;'>t</span><span
                    style='color:#ffff00;font-weight:bold;'>s</span></a></td>
        <td>10</td>
        <td>8736.640</td>
        <td>524.800</td>
    </tr>
    <tr>
        <td>594</td>
        <td><a href=players.php?pid=2062&edition=5><span style='color:#cc00ff;'>po</span><span
                    style='color:#dd00ff;'>tezn</span><span style='color:#ee00ff;'>ygej</span><span
                    style='color:#ff00ff;'>uwu</span></a></td>
        <td>10</td>
        <td>8736.960</td>
        <td>527.200</td>
    </tr>
    <tr>
        <td>595</td>
        <td><a href=players.php?pid=14019&edition=5><span style='color:#aaddee;'>e</span><span
                    style='color:#aadddd;'>l</span><span style='color:#aaeecc;'>e</span><span
                    style='color:#99eebb;'>v</span><span style='color:#99ffaa;'>e</span><span
                    style='color:#99ff99;'>n</span></a></td>
        <td>10</td>
        <td>8737.573</td>
        <td>531.800</td>
    </tr>
    <tr>
        <td>596</td>
        <td><a href=players.php?pid=7555&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;Vesfale</span></a></td>
        <td>10</td>
        <td>8739.293</td>
        <td>544.700</td>
    </tr>
    <tr>
        <td>597</td>
        <td><a href=players.php?pid=66910&edition=5>agar02_</a></td>
        <td>10</td>
        <td>8739.333</td>
        <td>545.000</td>
    </tr>
    <tr>
        <td>598</td>
        <td><a href=players.php?pid=51447&edition=5>Palx</a></td>
        <td>10</td>
        <td>8740.387</td>
        <td>552.900</td>
    </tr>
    <tr>
        <td>599</td>
        <td><a href=players.php?pid=56353&edition=5>gijsvanl7</a></td>
        <td>10</td>
        <td>8740.827</td>
        <td>556.200</td>
    </tr>
    <tr>
        <td>600</td>
        <td><a href=players.php?pid=21846&edition=5>Eintrachtffm97</a></td>
        <td>10</td>
        <td>8742.147</td>
        <td>566.100</td>
    </tr>
    <tr>
        <td>601</td>
        <td><a href=players.php?pid=33948&edition=5>BigBoyFatBob</a></td>
        <td>10</td>
        <td>8743.427</td>
        <td>575.700</td>
    </tr>
    <tr>
        <td>602</td>
        <td><a href=players.php?pid=9671&edition=5>GalvanTM</a></td>
        <td>10</td>
        <td>8743.653</td>
        <td>577.400</td>
    </tr>
    <tr>
        <td>603</td>
        <td><a href=players.php?pid=7893&edition=5><span style='color:#ffccee;'>Way</span><span
                    style='color:#dddddd;'>Too</span><span style='color:#ffccee;'>Average</span></a></td>
        <td>10</td>
        <td>8744.693</td>
        <td>585.200</td>
    </tr>
    <tr>
        <td>604</td>
        <td><a href=players.php?pid=60856&edition=5>SullyTM.</a></td>
        <td>10</td>
        <td>8744.760</td>
        <td>585.700</td>
    </tr>
    <tr>
        <td>605</td>
        <td><a href=players.php?pid=15580&edition=5><span style='color:#ffffff;'>Raydox.</span><span
                    style='color:#ccccff;'>K</span><span style='color:#ccccff;'>a</span><span
                    style='color:#bbbbff;'>c</span><span style='color:#bb99ff;'>c</span><span
                    style='color:#aa88ff;'>h</span><span style='color:#9966ff;'>i</span></a></td>
        <td>10</td>
        <td>8745.493</td>
        <td>591.200</td>
    </tr>
    <tr>
        <td>606</td>
        <td><a href=players.php?pid=67821&edition=5><span style='color:#ff0000;'>o</span><span
                    style='color:#ff1100;'>s</span><span style='color:#ff2200;'>t</span><span
                    style='color:#ff3300;'>el</span><span style='color:#ff4400;'>i</span><span
                    style='color:#ff5500;'>t</span><span style='color:#ff6600;'>o</span></a></td>
        <td>10</td>
        <td>8747.747</td>
        <td>608.100</td>
    </tr>
    <tr>
        <td>607</td>
        <td><a href=players.php?pid=68813&edition=5>Panaeolus.</a></td>
        <td>10</td>
        <td>8750.213</td>
        <td>626.600</td>
    </tr>
    <tr>
        <td>608</td>
        <td><a href=players.php?pid=58201&edition=5>joscha.</a></td>
        <td>10</td>
        <td>8751.853</td>
        <td>638.900</td>
    </tr>
    <tr>
        <td>609</td>
        <td><a href=players.php?pid=53522&edition=5><span style='color:#1177ff;font-style:italic;'>M</span><span
                    style='color:#2288ee;font-style:italic;'>a</span><span
                    style='color:#2299ee;font-style:italic;'>s</span><span
                    style='color:#22aadd;font-style:italic;'>t</span><span
                    style='color:#33bbcc;font-style:italic;'>e</span><span
                    style='color:#33cccc;font-style:italic;'>r</span><span
                    style='color:#33cccc;font-style:italic;'>b</span><span
                    style='color:#33ccaa;font-style:italic;'>o</span><span
                    style='color:#33bb77;font-style:italic;'>b</span><span
                    style='color:#33aa55;font-style:italic;'>o</span><span
                    style='color:#33aa33;font-style:italic;'>4</span><span
                    style='color:#339911;font-style:italic;'>7</span></a></td>
        <td>10</td>
        <td>8753.960</td>
        <td>654.700</td>
    </tr>
    <tr>
        <td>610</td>
        <td><a href=players.php?pid=32810&edition=5>bakanino</a></td>
        <td>10</td>
        <td>8755.347</td>
        <td>665.100</td>
    </tr>
    <tr>
        <td>611</td>
        <td><a href=players.php?pid=490&edition=5>gargiTM</a></td>
        <td>9</td>
        <td>8821.640</td>
        <td>180.333</td>
    </tr>
    <tr>
        <td>612</td>
        <td><a href=players.php?pid=68599&edition=5>&nbsp;<span
                    style='color:#777788;font-style:italic;font-weight:bold;'>778</span><span
                    style='color:#ffffff;font-style:italic;font-weight:bold;'>obake</span><span
                    style='color:#777788;font-style:italic;font-weight:bold;'>・</span></a></td>
        <td>9</td>
        <td>8832.000</td>
        <td>266.667</td>
    </tr>
    <tr>
        <td>613</td>
        <td><a href=players.php?pid=9930&edition=5><span style='color:#99ffff;'>ษ</span><span
                    style='color:#aaffee;'>Ӥ</span><span style='color:#aaffcc;'>Ά</span><span
                    style='color:#bbffbb;'>义</span><span style='color:#bbff99;'>2</span><span
                    style='color:#ccff88;'>6</span><span style='color:#ddff66;'>2</span>0<span
                    style='color:#eeff33;'>3</span><span style='color:#eeff22;'>ｲ</span><span
                    style='color:#ffff00;'>&pi;</span></a></td>
        <td>9</td>
        <td>8833.147</td>
        <td>276.222</td>
    </tr>
    <tr>
        <td>614</td>
        <td><a href=players.php?pid=52538&edition=5><span style='color:#ffff00;'>H</span><span
                    style='color:#000000;'>D&nbsp;</span><span style='color:#009900;'>Ɗ</span><span
                    style='color:#11bb00;'>น</span><span style='color:#22cc00;'>м</span><span
                    style='color:#22ee00;'>ӎ</span><span style='color:#33ff00;'>ӌ</span></a></td>
        <td>9</td>
        <td>8835.067</td>
        <td>292.222</td>
    </tr>
    <tr>
        <td>615</td>
        <td><a href=players.php?pid=31881&edition=5>g0ka</a></td>
        <td>9</td>
        <td>8842.200</td>
        <td>351.667</td>
    </tr>
    <tr>
        <td>616</td>
        <td><a href=players.php?pid=28941&edition=5>Opera&nbsp;(not&nbsp;the&nbsp;browser&nbsp;ffs)</a></td>
        <td>9</td>
        <td>8842.813</td>
        <td>356.778</td>
    </tr>
    <tr>
        <td>617</td>
        <td><a href=players.php?pid=37829&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='font-style:italic;'>Potat:owo:&nbsp;</span></a></td>
        <td>9</td>
        <td>8843.773</td>
        <td>364.778</td>
    </tr>
    <tr>
        <td>618</td>
        <td><a href=players.php?pid=51703&edition=5>TheKingGumba</a></td>
        <td>9</td>
        <td>8844.973</td>
        <td>374.778</td>
    </tr>
    <tr>
        <td>619</td>
        <td><a href=players.php?pid=11183&edition=5>TrackmaniaSigma</a></td>
        <td>9</td>
        <td>8846.827</td>
        <td>390.222</td>
    </tr>
    <tr>
        <td>620</td>
        <td><a href=players.php?pid=53326&edition=5>IvelliosTheFox</a></td>
        <td>9</td>
        <td>8847.347</td>
        <td>394.556</td>
    </tr>
    <tr>
        <td>621</td>
        <td><a href=players.php?pid=64863&edition=5><span style='color:#ff9900;'>B</span><span
                    style='color:#ff9911;'>iS</span><span style='color:#ff9922;'>aX</span><span
                    style='color:#ff9933;'>a</span></a></td>
        <td>9</td>
        <td>8848.187</td>
        <td>401.556</td>
    </tr>
    <tr>
        <td>622</td>
        <td><a href=players.php?pid=29677&edition=5>Thomas30009</a></td>
        <td>9</td>
        <td>8848.200</td>
        <td>401.667</td>
    </tr>
    <tr>
        <td>623</td>
        <td><a href=players.php?pid=6660&edition=5>sհҽ&iacute;ղҽx</a></td>
        <td>9</td>
        <td>8848.680</td>
        <td>405.667</td>
    </tr>
    <tr>
        <td>624</td>
        <td><a href=players.php?pid=23489&edition=5>Scrapie99</a></td>
        <td>9</td>
        <td>8849.853</td>
        <td>415.444</td>
    </tr>
    <tr>
        <td>625</td>
        <td><a href=players.php?pid=57495&edition=5>MLGNate.</a></td>
        <td>9</td>
        <td>8850.467</td>
        <td>420.556</td>
    </tr>
    <tr>
        <td>626</td>
        <td><a href=players.php?pid=27974&edition=5>SashSilvah</a></td>
        <td>9</td>
        <td>8851.800</td>
        <td>431.667</td>
    </tr>
    <tr>
        <td>627</td>
        <td><a href=players.php?pid=69234&edition=5>blaizer</a></td>
        <td>9</td>
        <td>8851.920</td>
        <td>432.667</td>
    </tr>
    <tr>
        <td>628</td>
        <td><a href=players.php?pid=4307&edition=5>TrilluXe</a></td>
        <td>9</td>
        <td>8852.347</td>
        <td>436.222</td>
    </tr>
    <tr>
        <td>629</td>
        <td><a href=players.php?pid=12326&edition=5>Nuhwo</a></td>
        <td>9</td>
        <td>8853.573</td>
        <td>446.444</td>
    </tr>
    <tr>
        <td>630</td>
        <td><a href=players.php?pid=56243&edition=5><span style='color:#1199ff;'>D</span><span
                    style='color:#1199ff;font-weight:bold;'>&iota;sp</span><span
                    style='color:#3399cc;font-weight:bold;'>at</span><span style='color:#3399cc;'>&copy;</span><span
                    style='color:#3399cc;font-weight:bold;'>h</span>b</a></td>
        <td>9</td>
        <td>8854.027</td>
        <td>450.222</td>
    </tr>
    <tr>
        <td>631</td>
        <td><a href=players.php?pid=63769&edition=5>Mustard.tarts</a></td>
        <td>9</td>
        <td>8856.720</td>
        <td>472.667</td>
    </tr>
    <tr>
        <td>632</td>
        <td><a href=players.php?pid=16836&edition=5><span style='color:#000000;font-style:italic;'>e</span><span
                    style='color:#ff0000;font-style:italic;'>D</span><span
                    style='color:#000000;font-style:italic;'>en</span><span
                    style='color:#ff0000;font-style:italic;'>|</span><span
                    style='color:#ff0000;font-style:italic;'>'&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;Litello&nbsp;&nbsp;</span></a></td>
        <td>9</td>
        <td>8857.413</td>
        <td>478.444</td>
    </tr>
    <tr>
        <td>633</td>
        <td><a href=players.php?pid=51895&edition=5>Elconn9plus10</a></td>
        <td>9</td>
        <td>8858.400</td>
        <td>486.667</td>
    </tr>
    <tr>
        <td>634</td>
        <td><a href=players.php?pid=68117&edition=5><span style='color:#eeaa33;'>X</span><span
                    style='color:#ee9922;'>o</span><span style='color:#ee8822;'>m</span><span
                    style='color:#ee7722;'>e</span><span style='color:#ee6622;'>g</span><span
                    style='color:#ee5522;'>a</span><span style='color:#ee3311;'>3</span><span
                    style='color:#ff2211;'>4</span><span style='color:#ff1111;'>5</span></a></td>
        <td>9</td>
        <td>8858.880</td>
        <td>490.667</td>
    </tr>
    <tr>
        <td>635</td>
        <td><a href=players.php?pid=66275&edition=5><span style='color:#330066;'>H</span><span
                    style='color:#330088;'>a</span><span style='color:#3300aa;'>i</span><span
                    style='color:#3300cc;'>k</span><span style='color:#3300cc;'>i</span><span
                    style='color:#2255ee;'>n</span><span style='color:#0099ff;'>g</span></a></td>
        <td>9</td>
        <td>8859.333</td>
        <td>494.444</td>
    </tr>
    <tr>
        <td>636</td>
        <td><a href=players.php?pid=39325&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Sheetah&nbsp;</span></a></td>
        <td>9</td>
        <td>8859.347</td>
        <td>494.556</td>
    </tr>
    <tr>
        <td>637</td>
        <td><a href=players.php?pid=6817&edition=5>barocix</a></td>
        <td>9</td>
        <td>8862.747</td>
        <td>522.889</td>
    </tr>
    <tr>
        <td>638</td>
        <td><a href=players.php?pid=9980&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;leveau_tm</span></a></td>
        <td>9</td>
        <td>8862.893</td>
        <td>524.111</td>
    </tr>
    <tr>
        <td>639</td>
        <td><a href=players.php?pid=53171&edition=5><span style='color:#ffffff;'>m</span><span
                    style='color:#0000ff;'>l</span><span style='color:#ff0000;'>r</span></a></td>
        <td>9</td>
        <td>8863.333</td>
        <td>527.778</td>
    </tr>
    <tr>
        <td>640</td>
        <td><a href=players.php?pid=50793&edition=5><span style='color:#aa00ff;'>Dying</span><span
                    style='color:#ffffff;'>Matschmn</span></a></td>
        <td>9</td>
        <td>8864.000</td>
        <td>533.333</td>
    </tr>
    <tr>
        <td>641</td>
        <td><a href=players.php?pid=18268&edition=5>maxipaxitaxi</a></td>
        <td>9</td>
        <td>8868.893</td>
        <td>574.111</td>
    </tr>
    <tr>
        <td>642</td>
        <td><a href=players.php?pid=8915&edition=5>Reficul89</a></td>
        <td>9</td>
        <td>8869.867</td>
        <td>582.222</td>
    </tr>
    <tr>
        <td>643</td>
        <td><a href=players.php?pid=52903&edition=5>RoXxeeer</a></td>
        <td>9</td>
        <td>8871.013</td>
        <td>591.778</td>
    </tr>
    <tr>
        <td>644</td>
        <td><a href=players.php?pid=29962&edition=5>newimer</a></td>
        <td>9</td>
        <td>8878.533</td>
        <td>654.444</td>
    </tr>
    <tr>
        <td>645</td>
        <td><a href=players.php?pid=15923&edition=5>STr0H.</a></td>
        <td>9</td>
        <td>8878.960</td>
        <td>658.000</td>
    </tr>
    <tr>
        <td>646</td>
        <td><a href=players.php?pid=54118&edition=5><span style='font-weight:bold;'>ฬ</span>el<span
                    style='color:#ff6600;'>l</span>vos</a></td>
        <td>9</td>
        <td>8883.973</td>
        <td>699.778</td>
    </tr>
    <tr>
        <td>647</td>
        <td><a href=players.php?pid=32687&edition=5><span style='color:#66ff33;'>Rib</span><span
                    style='color:#66ff33;'>bit&nbsp;:concernFroge:</span></a></td>
        <td>9</td>
        <td>8888.120</td>
        <td>734.333</td>
    </tr>
    <tr>
        <td>648</td>
        <td><a href=players.php?pid=35808&edition=5>STRID:e:R</a></td>
        <td>8</td>
        <td>8948.280</td>
        <td>140.125</td>
    </tr>
    <tr>
        <td>649</td>
        <td><a href=players.php?pid=69145&edition=5>Korokiwi</a></td>
        <td>8</td>
        <td>8956.253</td>
        <td>214.875</td>
    </tr>
    <tr>
        <td>650</td>
        <td><a href=players.php?pid=70076&edition=5>dazed&nbsp;:wicked:</a></td>
        <td>8</td>
        <td>8958.547</td>
        <td>236.375</td>
    </tr>
    <tr>
        <td>651</td>
        <td><a href=players.php?pid=49605&edition=5>Turnipp_</a></td>
        <td>8</td>
        <td>8961.587</td>
        <td>264.875</td>
    </tr>
    <tr>
        <td>652</td>
        <td><a href=players.php?pid=21006&edition=5>menz</a></td>
        <td>8</td>
        <td>8966.560</td>
        <td>311.500</td>
    </tr>
    <tr>
        <td>653</td>
        <td><a href=players.php?pid=70012&edition=5>amGreedy</a></td>
        <td>8</td>
        <td>8968.493</td>
        <td>329.625</td>
    </tr>
    <tr>
        <td>654</td>
        <td><a href=players.php?pid=38409&edition=5><span style='color:#ff33cc;'>S</span><span
                    style='color:#dd44cc;'>e</span><span style='color:#bb55cc;'>t</span><span
                    style='color:#9966cc;'>t</span><span style='color:#9966cc;'>L</span><span
                    style='color:#cc55cc;'>S</span><span style='color:#ff33cc;'>D</span></a></td>
        <td>8</td>
        <td>8968.587</td>
        <td>330.500</td>
    </tr>
    <tr>
        <td>655</td>
        <td><a href=players.php?pid=65091&edition=5>JazzaMLG</a></td>
        <td>8</td>
        <td>8969.227</td>
        <td>336.500</td>
    </tr>
    <tr>
        <td>656</td>
        <td><a href=players.php?pid=65872&edition=5><span style='color:#0077dd;font-weight:bold;'>K</span><span
                    style='color:#0088ff;font-weight:bold;'>O</span><span
                    style='color:#2299ff;font-weight:bold;'>S</span><span
                    style='color:#44aaff;font-weight:bold;'>T</span><span
                    style='color:#77bbff;font-weight:bold;'>A</span><span
                    style='color:#99ccff;font-weight:bold;'>V</span><span
                    style='color:#bbddff;font-weight:bold;'>O</span><span
                    style='color:#ddeeff;font-weight:bold;'>R</span><span
                    style='color:#eeffff;font-weight:bold;'>A</span><span
                    style='color:#ffffff;font-weight:bold;'>S</span></a></td>
        <td>8</td>
        <td>8971.827</td>
        <td>360.875</td>
    </tr>
    <tr>
        <td>657</td>
        <td><a href=players.php?pid=69896&edition=5>jarzzoni</a></td>
        <td>8</td>
        <td>8973.760</td>
        <td>379.000</td>
    </tr>
    <tr>
        <td>658</td>
        <td><a href=players.php?pid=22440&edition=5><span style='color:#000099;'>ғ</span><span
                    style='color:#2233bb;'>я</span><span style='color:#4466cc;'>ł</span><span
                    style='color:#6699ee;'>Đ</span><span style='color:#6699ee;'>Ǥ</span><span
                    style='color:#99bbcc;'>乇</span><span style='color:#ccccaa;'>&nbsp;</span><span
                    style='color:#ffee88;'>&Sigma;</span></a></td>
        <td>8</td>
        <td>8975.760</td>
        <td>397.750</td>
    </tr>
    <tr>
        <td>659</td>
        <td><a href=players.php?pid=5858&edition=5>sepiiiiiiiii</a></td>
        <td>8</td>
        <td>8977.253</td>
        <td>411.750</td>
    </tr>
    <tr>
        <td>660</td>
        <td><a href=players.php?pid=31626&edition=5><span style='color:#330099;'>G</span><span
                    style='color:#2200bb;'>u</span><span style='color:#2200cc;'>c</span><span
                    style='color:#1100ee;'>c</span><span style='color:#0000ff;'>i</span><span
                    style='color:#0000ff;'>G</span><span style='color:#2200bb;'>l</span><span
                    style='color:#550088;'>y</span><span style='color:#770044;'>d</span><span
                    style='color:#990000;'>e</span></a></td>
        <td>8</td>
        <td>8978.573</td>
        <td>424.125</td>
    </tr>
    <tr>
        <td>661</td>
        <td><a href=players.php?pid=29384&edition=5>Suudo_W</a></td>
        <td>8</td>
        <td>8978.813</td>
        <td>426.375</td>
    </tr>
    <tr>
        <td>662</td>
        <td><a href=players.php?pid=4122&edition=5>Sauergurke_</a></td>
        <td>8</td>
        <td>8978.973</td>
        <td>427.875</td>
    </tr>
    <tr>
        <td>663</td>
        <td><a href=players.php?pid=67092&edition=5>HypobaricWolf</a></td>
        <td>8</td>
        <td>8980.547</td>
        <td>442.625</td>
    </tr>
    <tr>
        <td>664</td>
        <td><a href=players.php?pid=7588&edition=5>:business:&nbsp;<span style='color:#00ffff;'>A</span><span
                    style='color:#66ffff;'>i</span><span style='color:#ccffff;'>r</span></a></td>
        <td>8</td>
        <td>8980.800</td>
        <td>445.000</td>
    </tr>
    <tr>
        <td>665</td>
        <td><a href=players.php?pid=8127&edition=5><span style='color:#880099;'>X</span><span
                    style='color:#882299;'>i</span><span style='color:#884499;'>n</span><span
                    style='color:#886699;'>e</span><span style='color:#888899;'>r</span><span
                    style='color:#88aa99;'>a</span></a></td>
        <td>8</td>
        <td>8980.880</td>
        <td>445.750</td>
    </tr>
    <tr>
        <td>666</td>
        <td><a href=players.php?pid=28846&edition=5>funky_TM</a></td>
        <td>8</td>
        <td>8982.240</td>
        <td>458.500</td>
    </tr>
    <tr>
        <td>667</td>
        <td><a href=players.php?pid=70649&edition=5>happy</a></td>
        <td>8</td>
        <td>8983.800</td>
        <td>473.125</td>
    </tr>
    <tr>
        <td>668</td>
        <td><a href=players.php?pid=50004&edition=5>N5Production</a></td>
        <td>8</td>
        <td>8984.867</td>
        <td>483.125</td>
    </tr>
    <tr>
        <td>669</td>
        <td><a href=players.php?pid=32636&edition=5>MilkyFurry</a></td>
        <td>8</td>
        <td>8984.987</td>
        <td>484.250</td>
    </tr>
    <tr>
        <td>670</td>
        <td><a href=players.php?pid=36881&edition=5>lukkii96</a></td>
        <td>8</td>
        <td>8985.027</td>
        <td>484.625</td>
    </tr>
    <tr>
        <td>671</td>
        <td><a href=players.php?pid=62893&edition=5>Kahyros</a></td>
        <td>8</td>
        <td>8985.627</td>
        <td>490.250</td>
    </tr>
    <tr>
        <td>672</td>
        <td><a href=players.php?pid=67878&edition=5><span style='color:#0033ff;'>Krubi</span><span
                    style='color:#000088;'>TM</span></a></td>
        <td>8</td>
        <td>8985.733</td>
        <td>491.250</td>
    </tr>
    <tr>
        <td>673</td>
        <td><a href=players.php?pid=11151&edition=5>Ben-Bandoo</a></td>
        <td>8</td>
        <td>8985.893</td>
        <td>492.750</td>
    </tr>
    <tr>
        <td>674</td>
        <td><a href=players.php?pid=20871&edition=5>jackmol24</a></td>
        <td>8</td>
        <td>8986.747</td>
        <td>500.750</td>
    </tr>
    <tr>
        <td>675</td>
        <td><a href=players.php?pid=33979&edition=5>b<span
                    style='color:#ff00ff;font-style:italic;'>&nbsp;POULE&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;HeadSmokeer</span></a></td>
        <td>8</td>
        <td>8986.947</td>
        <td>502.625</td>
    </tr>
    <tr>
        <td>676</td>
        <td><a href=players.php?pid=4617&edition=5>JOY-BOY-TM</a></td>
        <td>8</td>
        <td>8987.080</td>
        <td>503.875</td>
    </tr>
    <tr>
        <td>677</td>
        <td><a href=players.php?pid=10731&edition=5>MacDouken</a></td>
        <td>8</td>
        <td>8987.907</td>
        <td>511.625</td>
    </tr>
    <tr>
        <td>678</td>
        <td><a href=players.php?pid=12444&edition=5>BathOfPixels</a></td>
        <td>8</td>
        <td>8988.173</td>
        <td>514.125</td>
    </tr>
    <tr>
        <td>679</td>
        <td><a href=players.php?pid=9830&edition=5><span style='color:#ffffff;'>A</span><span
                    style='color:#ccffff;'>y</span><span style='color:#aaffee;'>h</span><span
                    style='color:#77eeee;'>o</span><span style='color:#44eedd;'>n</span></a></td>
        <td>8</td>
        <td>8990.000</td>
        <td>531.250</td>
    </tr>
    <tr>
        <td>680</td>
        <td><a href=players.php?pid=9342&edition=5><span style='color:#006633;'>Ɛlip</span><span
                    style='color:#cc3333;'>sion</span></a></td>
        <td>8</td>
        <td>8991.227</td>
        <td>542.750</td>
    </tr>
    <tr>
        <td>681</td>
        <td><a href=players.php?pid=9677&edition=5>Kones-</a></td>
        <td>8</td>
        <td>8991.787</td>
        <td>548.000</td>
    </tr>
    <tr>
        <td>682</td>
        <td><a href=players.php?pid=200&edition=5><span style='color:#ff00ff;font-weight:bold;'>Nitixd</span></a></td>
        <td>8</td>
        <td>8991.973</td>
        <td>549.750</td>
    </tr>
    <tr>
        <td>683</td>
        <td><a href=players.php?pid=46650&edition=5>chimmieharvekoi</a></td>
        <td>8</td>
        <td>8992.040</td>
        <td>550.375</td>
    </tr>
    <tr>
        <td>684</td>
        <td><a href=players.php?pid=64742&edition=5><span style='color:#99ff33;font-weight:bold;'>Ctrl</span><span
                    style='color:#006600;font-weight:bold;'>Shift</span><span
                    style='color:#ffff99;font-weight:bold;'>DAD</span></a></td>
        <td>8</td>
        <td>8992.093</td>
        <td>550.875</td>
    </tr>
    <tr>
        <td>685</td>
        <td><a href=players.php?pid=11254&edition=5><span style='color:#99ffff;'>s</span><span
                    style='color:#88ddff;'>c</span><span style='color:#66bbff;'>o</span><span
                    style='color:#5599ff;'>p</span><span style='color:#3377ff;'>e</span><span
                    style='color:#2255ff;'>2</span><span style='color:#0033ff;'>8</span></a></td>
        <td>8</td>
        <td>8992.520</td>
        <td>554.875</td>
    </tr>
    <tr>
        <td>686</td>
        <td><a href=players.php?pid=66160&edition=5>STAND_by_MODUS</a></td>
        <td>8</td>
        <td>8992.640</td>
        <td>556.000</td>
    </tr>
    <tr>
        <td>687</td>
        <td><a href=players.php?pid=33656&edition=5>Sir&nbsp;Raupe</a></td>
        <td>8</td>
        <td>8993.320</td>
        <td>562.375</td>
    </tr>
    <tr>
        <td>688</td>
        <td><a href=players.php?pid=70606&edition=5>DrunkLampCat</a></td>
        <td>8</td>
        <td>8993.653</td>
        <td>565.500</td>
    </tr>
    <tr>
        <td>689</td>
        <td><a href=players.php?pid=52304&edition=5><span style='color:#009900;'>D</span><span
                    style='color:#22aa22;'>E</span><span style='color:#33bb33;'>G</span><span
                    style='color:#55bb55;'>S</span><span style='color:#66cc66;'>&nbsp;</span><span
                    style='color:#ffffff;'>Elpepitio</span></a></td>
        <td>8</td>
        <td>8993.840</td>
        <td>567.250</td>
    </tr>
    <tr>
        <td>690</td>
        <td><a href=players.php?pid=2858&edition=5>LarsK1103</a></td>
        <td>8</td>
        <td>8994.733</td>
        <td>575.625</td>
    </tr>
    <tr>
        <td>691</td>
        <td><a href=players.php?pid=120&edition=5><span style='color:#000088;'>T</span><span
                    style='color:#5555aa;'>R</span><span style='color:#aaaadd;'>I</span><span
                    style='color:#ffffff;'>L</span><span style='color:#ffffff;'>L</span><span
                    style='color:#eeaabb;'>E</span><span style='color:#ee6677;'>K</span><span
                    style='color:#dd1133;'>S</span></a></td>
        <td>8</td>
        <td>8995.027</td>
        <td>578.375</td>
    </tr>
    <tr>
        <td>692</td>
        <td><a href=players.php?pid=7362&edition=5>Ruddy100</a></td>
        <td>8</td>
        <td>8995.720</td>
        <td>584.875</td>
    </tr>
    <tr>
        <td>693</td>
        <td><a href=players.php?pid=59629&edition=5>Navatak_</a></td>
        <td>8</td>
        <td>8996.200</td>
        <td>589.375</td>
    </tr>
    <tr>
        <td>694</td>
        <td><a href=players.php?pid=32900&edition=5>aBadPCGamer</a></td>
        <td>8</td>
        <td>8997.653</td>
        <td>603.000</td>
    </tr>
    <tr>
        <td>695</td>
        <td><a href=players.php?pid=18244&edition=5><span style='color:#ffffff;'>W</span><span
                    style='color:#eeccee;'>h</span><span style='color:#ee99ee;'>i</span><span
                    style='color:#dd66dd;'>t</span><span style='color:#dd33dd;'>e</span><span
                    style='color:#cc00cc;'>-</span><span style='color:#cc00cc;'>F</span><span
                    style='color:#990099;'>o</span><span style='color:#660066;'>x</span><span
                    style='color:#330033;'>T</span><span style='color:#000000;'>M</span></a></td>
        <td>8</td>
        <td>8999.040</td>
        <td>616.000</td>
    </tr>
    <tr>
        <td>696</td>
        <td><a href=players.php?pid=33494&edition=5>Frimmah</a></td>
        <td>8</td>
        <td>8999.293</td>
        <td>618.375</td>
    </tr>
    <tr>
        <td>697</td>
        <td><a href=players.php?pid=67319&edition=5><span style='color:#333399;'>s</span><span
                    style='color:#3333aa;'>i</span><span style='color:#3333bb;'>g</span><span
                    style='color:#3333dd;'>n</span><span style='color:#3333ee;'>a</span><span
                    style='color:#3333ff;'>l</span></a></td>
        <td>8</td>
        <td>8999.360</td>
        <td>619.000</td>
    </tr>
    <tr>
        <td>698</td>
        <td><a href=players.php?pid=41573&edition=5>Yeuss44</a></td>
        <td>8</td>
        <td>8999.947</td>
        <td>624.500</td>
    </tr>
    <tr>
        <td>699</td>
        <td><a href=players.php?pid=66755&edition=5>Pebless</a></td>
        <td>8</td>
        <td>9001.107</td>
        <td>635.375</td>
    </tr>
    <tr>
        <td>700</td>
        <td><a href=players.php?pid=66432&edition=5>Mayonais1850</a></td>
        <td>8</td>
        <td>9001.160</td>
        <td>635.875</td>
    </tr>
    <tr>
        <td>701</td>
        <td><a href=players.php?pid=58754&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;M4g1kFlo</span></a></td>
        <td>8</td>
        <td>9002.187</td>
        <td>645.500</td>
    </tr>
    <tr>
        <td>702</td>
        <td><a href=players.php?pid=55083&edition=5>Seemonn.</a></td>
        <td>8</td>
        <td>9002.880</td>
        <td>652.000</td>
    </tr>
    <tr>
        <td>703</td>
        <td><a href=players.php?pid=34657&edition=5><span style='color:#ff66cc;'>N</span><span
                    style='color:#ff55bb;'>i</span><span style='color:#ff3399;'>k</span>0<span
                    style='color:#ff0066;'>5</span></a></td>
        <td>8</td>
        <td>9003.453</td>
        <td>657.375</td>
    </tr>
    <tr>
        <td>704</td>
        <td><a href=players.php?pid=13792&edition=5>JeremZzzer</a></td>
        <td>8</td>
        <td>9004.200</td>
        <td>664.375</td>
    </tr>
    <tr>
        <td>705</td>
        <td><a href=players.php?pid=27785&edition=5><span style='color:#3399ff;'>c</span><span
                    style='color:#33ccee;'>a</span><span style='color:#33ffcc;'>n</span><span
                    style='color:#33ffcc;'>d</span><span style='color:#99ffff;'>o</span></a></td>
        <td>8</td>
        <td>9005.640</td>
        <td>677.875</td>
    </tr>
    <tr>
        <td>706</td>
        <td><a href=players.php?pid=55895&edition=5>GrimPeeves</a></td>
        <td>8</td>
        <td>9010.053</td>
        <td>719.250</td>
    </tr>
    <tr>
        <td>707</td>
        <td><a href=players.php?pid=33022&edition=5>b<span
                    style='color:#ff00ff;font-style:italic;'>&nbsp;POULE&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;Hexakil&nbsp;</span></a></td>
        <td>8</td>
        <td>9013.867</td>
        <td>755.000</td>
    </tr>
    <tr>
        <td>708</td>
        <td><a href=players.php?pid=64950&edition=5><span style='color:#ff3300;'>B</span><span
                    style='color:#ff6633;'>e</span><span style='color:#ff9966;'>t</span><span
                    style='color:#ff9966;'>o</span><span style='color:#ffccbb;'>j</span><span
                    style='color:#ffffff;'>o</span></a></td>
        <td>7</td>
        <td>9086.027</td>
        <td>207.429</td>
    </tr>
    <tr>
        <td>709</td>
        <td><a href=players.php?pid=62525&edition=5><span style='color:#ffbb00;'>s</span><span
                    style='color:#ffbb00;'>&dagger;</span><span style='color:#ffdd00;'>e</span><span
                    style='color:#ffee00;'>e</span><span style='color:#ffff00;'>l</span></a></td>
        <td>7</td>
        <td>9087.320</td>
        <td>221.286</td>
    </tr>
    <tr>
        <td>710</td>
        <td><a href=players.php?pid=28346&edition=5>П&Lambda;Ƭ&Sigma;</a></td>
        <td>7</td>
        <td>9088.480</td>
        <td>233.714</td>
    </tr>
    <tr>
        <td>711</td>
        <td><a href=players.php?pid=51795&edition=5><span
                    style='color:#9933bb;font-style:italic;font-weight:bold;'>O</span><span
                    style='color:#9944aa;font-style:italic;font-weight:bold;'>w</span><span
                    style='color:#aa6688;font-style:italic;font-weight:bold;'>l</span><span
                    style='color:#bb7766;font-style:italic;font-weight:bold;'>s</span><span
                    style='color:#bb9955;font-style:italic;font-weight:bold;'>A</span><span
                    style='color:#ccaa33;font-style:italic;font-weight:bold;'>r</span><span
                    style='color:#ccbb22;font-style:italic;font-weight:bold;'>e</span><span
                    style='color:#ccbb22;font-style:italic;font-weight:bold;'>V</span><span
                    style='color:#ddaa22;font-style:italic;font-weight:bold;'>e</span><span
                    style='color:#dd9922;font-style:italic;font-weight:bold;'>r</span><span
                    style='color:#dd7722;font-style:italic;font-weight:bold;'>y</span><span
                    style='color:#ee6622;font-style:italic;font-weight:bold;'>C</span><span
                    style='color:#ee5522;font-style:italic;font-weight:bold;'>o</span><span
                    style='color:#ee3333;font-style:italic;font-weight:bold;'>o</span><span
                    style='color:#ee2233;font-style:italic;font-weight:bold;'>l</span></a></td>
        <td>7</td>
        <td>9092.920</td>
        <td>281.286</td>
    </tr>
    <tr>
        <td>712</td>
        <td><a href=players.php?pid=61700&edition=5><span
                    style='color:#ff0000;font-style:italic;'>&nbsp;Thounej</span></a></td>
        <td>7</td>
        <td>9093.427</td>
        <td>286.714</td>
    </tr>
    <tr>
        <td>713</td>
        <td><a href=players.php?pid=33510&edition=5><span style='color:#ffaa00;'>✔</span><span
                    style='color:#ffaa00;'>v</span><span style='color:#ff9900;'>a</span><span
                    style='color:#ff9900;'>y</span><span style='color:#ff9900;'>s</span><span
                    style='color:#ff8800;'>e</span><span style='color:#ff8800;'>e</span></a></td>
        <td>7</td>
        <td>9095.520</td>
        <td>309.143</td>
    </tr>
    <tr>
        <td>714</td>
        <td><a href=players.php?pid=51852&edition=5><span style='color:#660000;'>B</span><span
                    style='color:#990000;'>A</span><span style='color:#ff9999;'>C</span><span
                    style='color:#660000;'>O</span><span style='color:#993333;'>N</span></a></td>
        <td>7</td>
        <td>9095.640</td>
        <td>310.429</td>
    </tr>
    <tr>
        <td>715</td>
        <td><a href=players.php?pid=30165&edition=5>Belabruce</a></td>
        <td>7</td>
        <td>9096.320</td>
        <td>317.714</td>
    </tr>
    <tr>
        <td>716</td>
        <td><a href=players.php?pid=5142&edition=5><span style='color:#ffff00;'>Loght&nbsp;</span></a></td>
        <td>7</td>
        <td>9096.347</td>
        <td>318.000</td>
    </tr>
    <tr>
        <td>717</td>
        <td><a href=players.php?pid=30211&edition=5>winged_TM</a></td>
        <td>7</td>
        <td>9097.027</td>
        <td>325.286</td>
    </tr>
    <tr>
        <td>718</td>
        <td><a href=players.php?pid=20855&edition=5>Trevligscarfs</a></td>
        <td>7</td>
        <td>9098.347</td>
        <td>339.429</td>
    </tr>
    <tr>
        <td>719</td>
        <td><a href=players.php?pid=31349&edition=5><span style='color:#ffddbb;'>y</span><span
                    style='color:#eebbbb;'>e</span><span style='color:#cc99bb;'>i</span><span
                    style='color:#bb66bb;'>w</span><span style='color:#9944bb;'>i</span><span
                    style='color:#8822bb;'>n</span></a></td>
        <td>7</td>
        <td>9099.987</td>
        <td>357.000</td>
    </tr>
    <tr>
        <td>720</td>
        <td><a href=players.php?pid=11172&edition=5>Blobritto</a></td>
        <td>7</td>
        <td>9100.147</td>
        <td>358.714</td>
    </tr>
    <tr>
        <td>721</td>
        <td><a href=players.php?pid=1821&edition=5>Zeerq.</a></td>
        <td>7</td>
        <td>9100.827</td>
        <td>366.000</td>
    </tr>
    <tr>
        <td>722</td>
        <td><a href=players.php?pid=23494&edition=5>millano10</a></td>
        <td>7</td>
        <td>9102.600</td>
        <td>385.000</td>
    </tr>
    <tr>
        <td>723</td>
        <td><a href=players.php?pid=66190&edition=5>aug.xst</a></td>
        <td>7</td>
        <td>9103.200</td>
        <td>391.429</td>
    </tr>
    <tr>
        <td>724</td>
        <td><a href=players.php?pid=62531&edition=5>Wazza__p</a></td>
        <td>7</td>
        <td>9103.733</td>
        <td>397.143</td>
    </tr>
    <tr>
        <td>725</td>
        <td><a href=players.php?pid=6301&edition=5><span style='color:#ffcc00;'>[75]</span><span
                    style='color:#ffffff;'>&nbsp;Pizza_1337</span></a></td>
        <td>7</td>
        <td>9103.933</td>
        <td>399.286</td>
    </tr>
    <tr>
        <td>726</td>
        <td><a href=players.php?pid=56498&edition=5><span style='color:#ff0000;font-style:italic;'>James</span><span
                    style='color:#eeeeee;font-style:italic;'>Roger</span><span
                    style='color:#3333ee;font-style:italic;'>Charles</span></a></td>
        <td>7</td>
        <td>9104.733</td>
        <td>407.857</td>
    </tr>
    <tr>
        <td>727</td>
        <td><a href=players.php?pid=11542&edition=5><span style='color:#3333cc;'>Z</span><span
                    style='color:#772288;'>y</span><span style='color:#bb1144;'>v</span><span
                    style='color:#ff0000;'>z</span></a></td>
        <td>7</td>
        <td>9105.133</td>
        <td>412.143</td>
    </tr>
    <tr>
        <td>728</td>
        <td><a href=players.php?pid=66954&edition=5>noahflex5</a></td>
        <td>7</td>
        <td>9105.587</td>
        <td>417.000</td>
    </tr>
    <tr>
        <td>729</td>
        <td><a href=players.php?pid=68652&edition=5>Gmatyas0</a></td>
        <td>7</td>
        <td>9105.987</td>
        <td>421.286</td>
    </tr>
    <tr>
        <td>730</td>
        <td><a href=players.php?pid=66630&edition=5>sparkysmith1</a></td>
        <td>7</td>
        <td>9106.680</td>
        <td>428.714</td>
    </tr>
    <tr>
        <td>731</td>
        <td><a href=players.php?pid=11476&edition=5><span style='color:#ff00ff;'>Doll</span><span
                    style='color:#ff00ff;font-weight:bold;'>O</span></a></td>
        <td>7</td>
        <td>9108.027</td>
        <td>443.143</td>
    </tr>
    <tr>
        <td>732</td>
        <td><a href=players.php?pid=54931&edition=5>AXYLDev</a></td>
        <td>7</td>
        <td>9109.080</td>
        <td>454.429</td>
    </tr>
    <tr>
        <td>733</td>
        <td><a href=players.php?pid=39494&edition=5>awepi</a></td>
        <td>7</td>
        <td>9109.147</td>
        <td>455.143</td>
    </tr>
    <tr>
        <td>734</td>
        <td><a href=players.php?pid=42527&edition=5>iYosh1337</a></td>
        <td>7</td>
        <td>9109.587</td>
        <td>459.857</td>
    </tr>
    <tr>
        <td>735</td>
        <td><a href=players.php?pid=9829&edition=5><span style='color:#0066ff;'>E</span><span
                    style='color:#8833ee;'>N</span><span style='color:#ff00cc;'>ﾋ</span><span
                    style='color:#ff00cc;'>E</span><span style='color:#880066;'>_</span><span
                    style='color:#000000;'>&trade;</span></a></td>
        <td>7</td>
        <td>9110.227</td>
        <td>466.714</td>
    </tr>
    <tr>
        <td>736</td>
        <td><a href=players.php?pid=12754&edition=5>l0ock</a></td>
        <td>7</td>
        <td>9110.720</td>
        <td>472.000</td>
    </tr>
    <tr>
        <td>737</td>
        <td><a href=players.php?pid=67059&edition=5><span style='color:#bb2255;'>S</span><span
                    style='color:#aa3366;'>m</span><span style='color:#aa3377;'>a</span><span
                    style='color:#994488;'>s</span><span style='color:#884499;'>h</span><span
                    style='color:#7744aa;'>T</span><span style='color:#6655bb;'>h</span><span
                    style='color:#5555cc;'>e</span><span style='color:#4466cc;'>G</span><span
                    style='color:#3366dd;'>o</span><span style='color:#2277ee;'>a</span><span
                    style='color:#1177ff;'>t</span></a></td>
        <td>7</td>
        <td>9111.227</td>
        <td>477.429</td>
    </tr>
    <tr>
        <td>738</td>
        <td><a href=players.php?pid=4168&edition=5>Papa_Kleine</a></td>
        <td>7</td>
        <td>9111.707</td>
        <td>482.571</td>
    </tr>
    <tr>
        <td>739</td>
        <td><a href=players.php?pid=62272&edition=5><span style='color:#66ffcc;'>d</span><span
                    style='color:#55ff99;'>ย</span><span style='color:#55ff66;'>Ć</span><span
                    style='color:#44ff33;'>Ҡ</span><span style='color:#33ff00;'>Y</span></a></td>
        <td>7</td>
        <td>9112.280</td>
        <td>488.714</td>
    </tr>
    <tr>
        <td>740</td>
        <td><a href=players.php?pid=40304&edition=5>Slatitude</a></td>
        <td>7</td>
        <td>9113.013</td>
        <td>496.571</td>
    </tr>
    <tr>
        <td>741</td>
        <td><a href=players.php?pid=70843&edition=5>Kamikalash</a></td>
        <td>7</td>
        <td>9113.387</td>
        <td>500.571</td>
    </tr>
    <tr>
        <td>742</td>
        <td><a href=players.php?pid=8904&edition=5>martinfromspb</a></td>
        <td>7</td>
        <td>9113.453</td>
        <td>501.286</td>
    </tr>
    <tr>
        <td>743</td>
        <td><a href=players.php?pid=122&edition=5>PorkyP</a></td>
        <td>7</td>
        <td>9114.347</td>
        <td>510.857</td>
    </tr>
    <tr>
        <td>744</td>
        <td><a href=players.php?pid=314&edition=5>Michmap</a></td>
        <td>7</td>
        <td>9114.400</td>
        <td>511.429</td>
    </tr>
    <tr>
        <td>745</td>
        <td><a href=players.php?pid=65220&edition=5>willy-wonka-</a></td>
        <td>7</td>
        <td>9114.920</td>
        <td>517.000</td>
    </tr>
    <tr>
        <td>746</td>
        <td><a href=players.php?pid=47010&edition=5>inzom</a></td>
        <td>7</td>
        <td>9115.213</td>
        <td>520.143</td>
    </tr>
    <tr>
        <td>747</td>
        <td><a href=players.php?pid=62739&edition=5>ttv.riversidetm</a></td>
        <td>7</td>
        <td>9115.253</td>
        <td>520.571</td>
    </tr>
    <tr>
        <td>748</td>
        <td><a href=players.php?pid=62006&edition=5><span style='color:#eeff00;font-style:italic;'>A</span><span
                    style='color:#ffffff;font-style:italic;'>stral</span><span
                    style='color:#eeff00;font-style:italic;'>&nbsp;</span><span
                    style='color:#eeff00;font-style:italic;'>&nbsp;UV</span></a></td>
        <td>7</td>
        <td>9115.547</td>
        <td>523.714</td>
    </tr>
    <tr>
        <td>749</td>
        <td><a href=players.php?pid=37731&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;AngurL</span></a></td>
        <td>7</td>
        <td>9115.640</td>
        <td>524.714</td>
    </tr>
    <tr>
        <td>750</td>
        <td><a href=players.php?pid=42626&edition=5>herecuzimbored</a></td>
        <td>7</td>
        <td>9116.307</td>
        <td>531.857</td>
    </tr>
    <tr>
        <td>751</td>
        <td><a href=players.php?pid=39691&edition=5><span style='color:#ff0000;'>M</span><span
                    style='color:#cc1133;'>a</span><span style='color:#991166;'>g</span><span
                    style='color:#662299;'>e</span><span style='color:#3322cc;'>T</span><span
                    style='color:#0033ff;'>M&nbsp;:xdd:</span></a></td>
        <td>7</td>
        <td>9116.440</td>
        <td>533.286</td>
    </tr>
    <tr>
        <td>752</td>
        <td><a href=players.php?pid=66718&edition=5>CamelloAffamato</a></td>
        <td>7</td>
        <td>9117.840</td>
        <td>548.286</td>
    </tr>
    <tr>
        <td>753</td>
        <td><a href=players.php?pid=10424&edition=5>MojMoj96</a></td>
        <td>7</td>
        <td>9117.973</td>
        <td>549.714</td>
    </tr>
    <tr>
        <td>754</td>
        <td><a href=players.php?pid=14505&edition=5>turvii</a></td>
        <td>7</td>
        <td>9118.280</td>
        <td>553.000</td>
    </tr>
    <tr>
        <td>755</td>
        <td><a href=players.php?pid=32210&edition=5>Idefelix</a></td>
        <td>7</td>
        <td>9118.293</td>
        <td>553.143</td>
    </tr>
    <tr>
        <td>756</td>
        <td><a href=players.php?pid=51677&edition=5><span style='color:#990099;'>B</span><span
                    style='color:#9900aa;'>o</span><span style='color:#9900bb;'>z</span><span
                    style='color:#9900cc;'>c</span><span style='color:#9900dd;'>a</span><span
                    style='color:#9900ee;'>p</span><span style='color:#9900ff;'>e</span></a></td>
        <td>7</td>
        <td>9119.040</td>
        <td>561.143</td>
    </tr>
    <tr>
        <td>757</td>
        <td><a href=players.php?pid=7279&edition=5><span style='color:#ffaa00;'>nitlit</span></a></td>
        <td>7</td>
        <td>9119.160</td>
        <td>562.429</td>
    </tr>
    <tr>
        <td>758</td>
        <td><a href=players.php?pid=12668&edition=5><span style='color:#009900;'>S</span><span
                    style='color:#22bb44;'>t</span><span style='color:#44dd88;'>e</span><span
                    style='color:#66ffcc;'>n</span><span style='color:#66ffcc;'>n</span><span
                    style='color:#bbff99;'>i</span><span style='color:#ffff66;'>s</span></a></td>
        <td>7</td>
        <td>9119.587</td>
        <td>567.000</td>
    </tr>
    <tr>
        <td>759</td>
        <td><a href=players.php?pid=68777&edition=5>IronBeagle0072</a></td>
        <td>7</td>
        <td>9119.787</td>
        <td>569.143</td>
    </tr>
    <tr>
        <td>760</td>
        <td><a href=players.php?pid=66164&edition=5><span style='color:#000000;font-weight:bold;'>O</span><span
                    style='color:#111111;font-weight:bold;'>z</span><span
                    style='color:#222222;font-weight:bold;'>z</span><span
                    style='color:#333333;font-weight:bold;'>i</span><span
                    style='color:#444444;font-weight:bold;'>e</span><span
                    style='color:#555555;font-weight:bold;'>O</span><span
                    style='color:#666666;font-weight:bold;'>n</span><span
                    style='color:#777777;font-weight:bold;'>B</span><span
                    style='color:#888888;font-weight:bold;'>a</span><span
                    style='color:#999999;font-weight:bold;'>s</span><span
                    style='color:#aaaaaa;font-weight:bold;'>s</span></a></td>
        <td>7</td>
        <td>9119.813</td>
        <td>569.429</td>
    </tr>
    <tr>
        <td>761</td>
        <td><a href=players.php?pid=54887&edition=5>LachyTM_</a></td>
        <td>7</td>
        <td>9119.947</td>
        <td>570.857</td>
    </tr>
    <tr>
        <td>762</td>
        <td><a href=players.php?pid=34759&edition=5>Wendigo_008</a></td>
        <td>7</td>
        <td>9120.560</td>
        <td>577.429</td>
    </tr>
    <tr>
        <td>763</td>
        <td><a href=players.php?pid=52437&edition=5><span style='color:#0033cc;'>凡</span><span
                    style='color:#557788;'>ů</span><span style='color:#aabb44;'>d</span><span
                    style='color:#ffff00;'>I</span></a></td>
        <td>7</td>
        <td>9121.320</td>
        <td>585.571</td>
    </tr>
    <tr>
        <td>764</td>
        <td><a href=players.php?pid=67656&edition=5>Tungdil_14</a></td>
        <td>7</td>
        <td>9122.280</td>
        <td>595.857</td>
    </tr>
    <tr>
        <td>765</td>
        <td><a href=players.php?pid=62305&edition=5>xtrevv</a></td>
        <td>7</td>
        <td>9125.693</td>
        <td>632.429</td>
    </tr>
    <tr>
        <td>766</td>
        <td><a href=players.php?pid=12739&edition=5><span style='color:#0033cc;'>T</span><span
                    style='color:#1155cc;'>r</span><span style='color:#2266dd;'>a</span><span
                    style='color:#3388dd;'>i</span><span style='color:#5599ee;'>n</span><span
                    style='color:#66bbee;'>e</span><span style='color:#77ccee;'>e</span><span
                    style='color:#88eeff;'>&nbsp;</span><span style='color:#99ffff;'>S</span><span
                    style='color:#99ffff;'>m</span><span style='color:#88ffdd;'>o</span><span
                    style='color:#77ffbb;'>k</span><span style='color:#66ff99;'>e</span><span
                    style='color:#55ff88;'>r</span><span style='color:#33ff66;'>N</span><span
                    style='color:#22ff44;'>i</span><span style='color:#11ff22;'>l</span><span
                    style='color:#00ff00;'>s</span></a></td>
        <td>7</td>
        <td>9126.720</td>
        <td>643.429</td>
    </tr>
    <tr>
        <td>767</td>
        <td><a href=players.php?pid=51723&edition=5>zmcd65</a></td>
        <td>7</td>
        <td>9127.107</td>
        <td>647.571</td>
    </tr>
    <tr>
        <td>768</td>
        <td><a href=players.php?pid=8572&edition=5><span style='color:#99ffff;'>G</span><span
                    style='color:#bbffff;'>l</span><span style='color:#ccffff;'>i</span><span
                    style='color:#ccffff;'>&fnof;</span><span style='color:#eeffee;'>t</span><span
                    style='color:#ffffcc;'>h</span></a></td>
        <td>7</td>
        <td>9127.853</td>
        <td>655.571</td>
    </tr>
    <tr>
        <td>769</td>
        <td><a href=players.php?pid=31767&edition=5><span style='color:#990000;font-weight:bold;'>🔥Z</span><span
                    style='color:#cc3300;font-weight:bold;'>i</span><span
                    style='color:#cc3300;font-weight:bold;'>f</span><span
                    style='color:#ff3300;font-weight:bold;'>l</span><span
                    style='color:#ff6600;font-weight:bold;'>a</span><span
                    style='color:#ff9900;font-weight:bold;'>m</span><span
                    style='color:#ffcc33;font-weight:bold;'>e🔥</span></a></td>
        <td>7</td>
        <td>9128.760</td>
        <td>665.286</td>
    </tr>
    <tr>
        <td>770</td>
        <td><a href=players.php?pid=1825&edition=5><span style='color:#aa55ee;'>E</span><span
                    style='color:#cc55ee;'>s</span><span style='color:#ee88ff;'>s</span><span
                    style='color:#ff99ff;'>z</span><span style='color:#ffeeff;'>z</span></a></td>
        <td>7</td>
        <td>9129.627</td>
        <td>674.571</td>
    </tr>
    <tr>
        <td>771</td>
        <td><a href=players.php?pid=46535&edition=5>DramerTM</a></td>
        <td>7</td>
        <td>9129.707</td>
        <td>675.429</td>
    </tr>
    <tr>
        <td>772</td>
        <td><a href=players.php?pid=54726&edition=5><span style='color:#0000cc;'>Ł</span><span
                    style='color:#0011dd;'>&sigma;</span><span style='color:#0022dd;'>&alpha;</span><span
                    style='color:#0033ee;'>ȡ</span><span style='color:#0044ee;'>ϊ</span><span
                    style='color:#0055ff;'>ก</span><span style='color:#0066ff;'>ǥ&nbsp;</span><span
                    style='color:#66ffff;'>々&nbsp;</span><span style='color:#ffffff;'>&not;&nbsp;</span><span
                    style='color:#ffcc00;'>Tomot&egrave;!</span></a></td>
        <td>7</td>
        <td>9130.653</td>
        <td>685.571</td>
    </tr>
    <tr>
        <td>773</td>
        <td><a href=players.php?pid=14549&edition=5>Unitedwdb</a></td>
        <td>7</td>
        <td>9131.067</td>
        <td>690.000</td>
    </tr>
    <tr>
        <td>774</td>
        <td><a href=players.php?pid=33442&edition=5><span style='color:#55ccff;'>愛</span><span
                    style='color:#eeaabb;'>音</span><span style='color:#ffffff;'>猫:smirkcat:</span></a></td>
        <td>7</td>
        <td>9131.413</td>
        <td>693.714</td>
    </tr>
    <tr>
        <td>775</td>
        <td><a href=players.php?pid=559&edition=5>Siegessch</a></td>
        <td>7</td>
        <td>9133.013</td>
        <td>710.857</td>
    </tr>
    <tr>
        <td>776</td>
        <td><a href=players.php?pid=71089&edition=5><span style='color:#00cccc;'>W</span><span
                    style='color:#66eeee;'>u</span><span style='color:#ccffff;'>m</span><span
                    style='color:#ccffff;'>w</span><span style='color:#ffffff;'>i</span></a></td>
        <td>7</td>
        <td>9137.013</td>
        <td>753.714</td>
    </tr>
    <tr>
        <td>777</td>
        <td><a href=players.php?pid=32330&edition=5>b<span
                    style='color:#ff00ff;font-style:italic;'>&nbsp;POULE&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;TheaPome&nbsp;</span></a></td>
        <td>7</td>
        <td>9142.427</td>
        <td>811.714</td>
    </tr>
    <tr>
        <td>778</td>
        <td><a href=players.php?pid=11920&edition=5>Smykketyven</a></td>
        <td>7</td>
        <td>9144.107</td>
        <td>829.714</td>
    </tr>
    <tr>
        <td>779</td>
        <td><a href=players.php?pid=63077&edition=5>DugonGOD</a></td>
        <td>6</td>
        <td>9205.920</td>
        <td>74.000</td>
    </tr>
    <tr>
        <td>780</td>
        <td><a href=players.php?pid=50445&edition=5><span style='color:#aa0000;'>&nbsp;</span><span
                    style='color:#aa0000;letter-spacing: -0.1em;font-size:smaller'>ॢ</span><span
                    style='color:#007766;'>St</span><span style='color:#008877;'>rat</span><span
                    style='color:#009988;'>os</span><span style='color:#ddaa00;'>Da</span><span
                    style='font-weight:bold;'>&nbsp;ア~ア</span></a></td>
        <td>6</td>
        <td>9213.733</td>
        <td>171.667</td>
    </tr>
    <tr>
        <td>781</td>
        <td><a href=players.php?pid=6180&edition=5><span style='color:#00cc99;font-style:italic;'>valent</span><span
                    style='color:#000000;font-style:italic;'>.</span><span
                    style='color:#ffffff;font-style:italic;'>.</span></a></td>
        <td>6</td>
        <td>9218.667</td>
        <td>233.333</td>
    </tr>
    <tr>
        <td>782</td>
        <td><a href=players.php?pid=43202&edition=5>:hmmnotes:&nbsp;:REEeee:</a></td>
        <td>6</td>
        <td>9218.880</td>
        <td>236.000</td>
    </tr>
    <tr>
        <td>783</td>
        <td><a href=players.php?pid=67992&edition=5>darkskittless</a></td>
        <td>6</td>
        <td>9222.453</td>
        <td>280.667</td>
    </tr>
    <tr>
        <td>784</td>
        <td><a href=players.php?pid=30196&edition=5>Mince</a></td>
        <td>6</td>
        <td>9222.947</td>
        <td>286.833</td>
    </tr>
    <tr>
        <td>785</td>
        <td><a href=players.php?pid=68177&edition=5>[45]&nbsp;Hollow</a></td>
        <td>6</td>
        <td>9222.960</td>
        <td>287.000</td>
    </tr>
    <tr>
        <td>786</td>
        <td><a href=players.php?pid=13016&edition=5>kwil<span style='color:#ff0055;'>o</span><span
                    style='color:#ffffff;'>.ev</span><span style='color:#ff0055;'>o</span></a></td>
        <td>6</td>
        <td>9223.040</td>
        <td>288.000</td>
    </tr>
    <tr>
        <td>787</td>
        <td><a href=players.php?pid=66593&edition=5>JanneBajkula</a></td>
        <td>6</td>
        <td>9224.387</td>
        <td>304.833</td>
    </tr>
    <tr>
        <td>788</td>
        <td><a href=players.php?pid=33840&edition=5>septym1</a></td>
        <td>6</td>
        <td>9224.987</td>
        <td>312.333</td>
    </tr>
    <tr>
        <td>789</td>
        <td><a href=players.php?pid=8927&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='color:#ff9900;font-style:italic;'>H</span><span
                    style='color:#ffaa11;font-style:italic;'>ѳ</span><span
                    style='color:#ffbb11;font-style:italic;'>Ŕ</span><span
                    style='color:#ffdd22;font-style:italic;'>&scaron;</span><span
                    style='color:#ffee22;font-style:italic;'>3</span><span
                    style='color:#ffff33;font-style:italic;'>Ғ</span><span
                    style='color:#ffff33;font-style:italic;'>Ĭ</span><span
                    style='color:#ffee22;font-style:italic;'>Ğ</span><span
                    style='color:#ffdd22;font-style:italic;'>Ή</span><span
                    style='color:#ffbb11;font-style:italic;'>ŧ</span><span
                    style='color:#ffaa11;font-style:italic;'>ė</span><span
                    style='color:#ff9900;font-style:italic;'>Ř</span></a></td>
        <td>6</td>
        <td>9225.933</td>
        <td>324.167</td>
    </tr>
    <tr>
        <td>790</td>
        <td><a href=players.php?pid=12911&edition=5>leoleodeodeo</a></td>
        <td>6</td>
        <td>9225.947</td>
        <td>324.333</td>
    </tr>
    <tr>
        <td>791</td>
        <td><a href=players.php?pid=25928&edition=5><span style='color:#000000;'>x</span><span
                    style='color:#ffffff;'>Emlan</span><span style='color:#000000;'>x</span></a></td>
        <td>6</td>
        <td>9226.813</td>
        <td>335.167</td>
    </tr>
    <tr>
        <td>792</td>
        <td><a href=players.php?pid=255&edition=5><span style='color:#0066cc;'>Ni</span><span
                    style='color:#0077cc;'>b</span><span style='color:#1177bb;'>a</span><span
                    style='color:#1188bb;'>r&nbsp;</span><span style='color:#1199bb;'>B</span><span
                    style='color:#2299bb;'>u</span><span style='color:#2299aa;'>z</span><span
                    style='color:#22aaaa;'>ya</span><span style='color:#22bbaa;'>i</span><span
                    style='color:#33bb99;'>g</span><span style='color:#33cc99;'>ri</span></a></td>
        <td>6</td>
        <td>9227.013</td>
        <td>337.667</td>
    </tr>
    <tr>
        <td>793</td>
        <td><a href=players.php?pid=66059&edition=5>Mr.SirPatty</a></td>
        <td>6</td>
        <td>9227.320</td>
        <td>341.500</td>
    </tr>
    <tr>
        <td>794</td>
        <td><a href=players.php?pid=66335&edition=5>borakeglya</a></td>
        <td>6</td>
        <td>9227.547</td>
        <td>344.333</td>
    </tr>
    <tr>
        <td>795</td>
        <td><a href=players.php?pid=6365&edition=5>shadecam&nbsp;&gt;&lt;&gt;</a></td>
        <td>6</td>
        <td>9228.480</td>
        <td>356.000</td>
    </tr>
    <tr>
        <td>796</td>
        <td><a href=players.php?pid=29154&edition=5>panKEKW</a></td>
        <td>6</td>
        <td>9229.920</td>
        <td>374.000</td>
    </tr>
    <tr>
        <td>797</td>
        <td><a href=players.php?pid=9771&edition=5>DominoMarama</a></td>
        <td>6</td>
        <td>9230.333</td>
        <td>379.167</td>
    </tr>
    <tr>
        <td>798</td>
        <td><a href=players.php?pid=40408&edition=5><span style='color:#ff00cc;'>x</span><span
                    style='color:#dd00aa;'>y</span><span style='color:#bb0088;'>l</span><span
                    style='color:#990066;'>z</span></a></td>
        <td>6</td>
        <td>9230.907</td>
        <td>386.333</td>
    </tr>
    <tr>
        <td>799</td>
        <td><a href=players.php?pid=42240&edition=5><span style='color:#ff66ff;'>M</span><span
                    style='color:#dd66ff;'>i</span><span style='color:#bb66ff;'>r</span><span
                    style='color:#9966ff;'>u</span></a></td>
        <td>6</td>
        <td>9231.613</td>
        <td>395.167</td>
    </tr>
    <tr>
        <td>800</td>
        <td><a href=players.php?pid=69075&edition=5>lOaOl.</a></td>
        <td>6</td>
        <td>9232.093</td>
        <td>401.167</td>
    </tr>
    <tr>
        <td>801</td>
        <td><a href=players.php?pid=6617&edition=5>ilkertarded</a></td>
        <td>6</td>
        <td>9232.613</td>
        <td>407.667</td>
    </tr>
    <tr>
        <td>802</td>
        <td><a href=players.php?pid=51751&edition=5>L</a></td>
        <td>6</td>
        <td>9232.987</td>
        <td>412.333</td>
    </tr>
    <tr>
        <td>803</td>
        <td><a href=players.php?pid=35237&edition=5>lenynou</a></td>
        <td>6</td>
        <td>9233.533</td>
        <td>419.167</td>
    </tr>
    <tr>
        <td>804</td>
        <td><a href=players.php?pid=58882&edition=5>E_The_Real</a></td>
        <td>6</td>
        <td>9234.413</td>
        <td>430.167</td>
    </tr>
    <tr>
        <td>805</td>
        <td><a href=players.php?pid=6482&edition=5>:dinkdonk:</a></td>
        <td>6</td>
        <td>9235.227</td>
        <td>440.333</td>
    </tr>
    <tr>
        <td>806</td>
        <td><a href=players.php?pid=50642&edition=5><span style='color:#000000;'>ȼh&iota;ı</span><span
                    style='color:#ff0000;'>ƄƦϘ</span></a></td>
        <td>6</td>
        <td>9235.587</td>
        <td>444.833</td>
    </tr>
    <tr>
        <td>807</td>
        <td><a href=players.php?pid=8023&edition=5>Razamin</a></td>
        <td>6</td>
        <td>9235.973</td>
        <td>449.667</td>
    </tr>
    <tr>
        <td>808</td>
        <td><a href=players.php?pid=36504&edition=5>dusmartijngams</a></td>
        <td>6</td>
        <td>9236.067</td>
        <td>450.833</td>
    </tr>
    <tr>
        <td>809</td>
        <td><a href=players.php?pid=9941&edition=5>Maxiguigui</a></td>
        <td>6</td>
        <td>9236.173</td>
        <td>452.167</td>
    </tr>
    <tr>
        <td>810</td>
        <td><a href=players.php?pid=30780&edition=5>MonkeyD.Talge</a></td>
        <td>6</td>
        <td>9236.400</td>
        <td>455.000</td>
    </tr>
    <tr>
        <td>811</td>
        <td><a href=players.php?pid=9816&edition=5>Lunaxz</a></td>
        <td>6</td>
        <td>9236.907</td>
        <td>461.333</td>
    </tr>
    <tr>
        <td>812</td>
        <td><a href=players.php?pid=17615&edition=5>:copium:&nbsp;<span style='color:#ff0000;'>d</span><span
                    style='color:#ee1100;'>ea</span><span style='color:#dd2200;'>l</span><span
                    style='color:#cc3300;'>e</span><span style='color:#bb4400;'>r&nbsp;</span><span
                    style='color:#aa5500;'>(</span><span style='color:#996600;'>ty</span><span
                    style='color:#887700;'>p</span><span style='color:#778800;'>e&nbsp;:ben:&nbsp;</span><span
                    style='color:#669900;'>f</span><span style='color:#55aa00;'>o</span><span
                    style='color:#44bb00;'>r&nbsp;:copium:&nbsp;</span><span style='color:#33cc00;'>)</span></a></td>
        <td>6</td>
        <td>9237.147</td>
        <td>464.333</td>
    </tr>
    <tr>
        <td>813</td>
        <td><a href=players.php?pid=40702&edition=5>lIgmAtitis</a></td>
        <td>6</td>
        <td>9237.613</td>
        <td>470.167</td>
    </tr>
    <tr>
        <td>814</td>
        <td><a href=players.php?pid=45449&edition=5>JacobJ2000</a></td>
        <td>6</td>
        <td>9238.387</td>
        <td>479.833</td>
    </tr>
    <tr>
        <td>815</td>
        <td><a href=players.php?pid=32025&edition=5><span
                    style='color:#0088ee;letter-spacing: -0.1em;font-size:smaller'>max</span><span
                    style='color:#ffff00;letter-spacing: -0.1em;font-size:smaller'>WellProduced</span></a></td>
        <td>6</td>
        <td>9239.000</td>
        <td>487.500</td>
    </tr>
    <tr>
        <td>816</td>
        <td><a href=players.php?pid=43030&edition=5><span style='color:#ff9900;font-weight:bold;'>smn</span></a></td>
        <td>6</td>
        <td>9239.347</td>
        <td>491.833</td>
    </tr>
    <tr>
        <td>817</td>
        <td><a href=players.php?pid=6837&edition=5>Klenne-</a></td>
        <td>6</td>
        <td>9239.867</td>
        <td>498.333</td>
    </tr>
    <tr>
        <td>818</td>
        <td><a href=players.php?pid=31568&edition=5><span style='color:#6600ff;'>S</span><span
                    style='color:#7700ff;'>q</span><span style='color:#8800ff;'>u</span><span
                    style='color:#9900ff;'>e</span><span style='color:#9900ff;'>k</span><span
                    style='color:#aa00ff;'>ky</span></a></td>
        <td>6</td>
        <td>9239.947</td>
        <td>499.333</td>
    </tr>
    <tr>
        <td>819</td>
        <td><a href=players.php?pid=14556&edition=5><span style='color:#0088ff;'>Green</span></a></td>
        <td>6</td>
        <td>9240.240</td>
        <td>503.000</td>
    </tr>
    <tr>
        <td>820</td>
        <td><a href=players.php?pid=54572&edition=5>[<span style='color:#ffff88;'>bruh</span><span
                    style='color:#ffffff;'>]Nuclear</span></a></td>
        <td>6</td>
        <td>9240.440</td>
        <td>505.500</td>
    </tr>
    <tr>
        <td>821</td>
        <td><a href=players.php?pid=33079&edition=5>SwedishPenguin_</a></td>
        <td>6</td>
        <td>9240.773</td>
        <td>509.667</td>
    </tr>
    <tr>
        <td>822</td>
        <td><a href=players.php?pid=34654&edition=5>Creaden37</a></td>
        <td>6</td>
        <td>9241.027</td>
        <td>512.833</td>
    </tr>
    <tr>
        <td>823</td>
        <td><a href=players.php?pid=51743&edition=5><span style='color:#0000dd;'>&raquo;ғฟ๏&laquo;&nbsp;</span>ii<span
                    style='color:#ffcc88;'>S</span><span style='font-style:italic;font-weight:bold;'>ฬ</span><span
                    style='font-style:italic;'>aиoo</span><span
                    style='color:#ff6688;font-weight:bold;'>_t</span>_900.TM</a></td>
        <td>6</td>
        <td>9241.360</td>
        <td>517.000</td>
    </tr>
    <tr>
        <td>824</td>
        <td><a href=players.php?pid=68663&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Siolgnal</span></a></td>
        <td>6</td>
        <td>9241.973</td>
        <td>524.667</td>
    </tr>
    <tr>
        <td>825</td>
        <td><a href=players.php?pid=45957&edition=5>makkapakka234</a></td>
        <td>6</td>
        <td>9242.413</td>
        <td>530.167</td>
    </tr>
    <tr>
        <td>826</td>
        <td><a href=players.php?pid=8795&edition=5>MchlWlrvn</a></td>
        <td>6</td>
        <td>9242.880</td>
        <td>536.000</td>
    </tr>
    <tr>
        <td>827</td>
        <td><a href=players.php?pid=52608&edition=5><span
                    style='color:#33ff33;font-style:italic;'>&nbsp;POULE&nbsp;|&nbsp;</span><span
                    style='color:#33ff33;font-style:italic;'>D</span><span
                    style='color:#ffffff;font-style:italic;'>a</span><span
                    style='color:#33ff33;font-style:italic;'>Z</span><span
                    style='color:#ffffff;font-style:italic;'>yster</span></a></td>
        <td>6</td>
        <td>9243.093</td>
        <td>538.667</td>
    </tr>
    <tr>
        <td>828</td>
        <td><a href=players.php?pid=26350&edition=5>Bobthepenguin2</a></td>
        <td>6</td>
        <td>9243.360</td>
        <td>542.000</td>
    </tr>
    <tr>
        <td>829</td>
        <td><a href=players.php?pid=49816&edition=5>Draxo.21</a></td>
        <td>6</td>
        <td>9243.427</td>
        <td>542.833</td>
    </tr>
    <tr>
        <td>830</td>
        <td><a href=players.php?pid=66382&edition=5>Danyy912</a></td>
        <td>6</td>
        <td>9244.187</td>
        <td>552.333</td>
    </tr>
    <tr>
        <td>831</td>
        <td><a href=players.php?pid=66400&edition=5>stokesy0807</a></td>
        <td>6</td>
        <td>9244.200</td>
        <td>552.500</td>
    </tr>
    <tr>
        <td>832</td>
        <td><a href=players.php?pid=61974&edition=5><span style='color:#ff00ff;'>Som</span><span
                    style='color:#ff00ff;'>p</span><span style='color:#9988ff;'>i</span><span
                    style='color:#33ffff;'>g</span></a></td>
        <td>6</td>
        <td>9244.293</td>
        <td>553.667</td>
    </tr>
    <tr>
        <td>833</td>
        <td><a href=players.php?pid=65300&edition=5>Grebbastuing</a></td>
        <td>6</td>
        <td>9244.973</td>
        <td>562.167</td>
    </tr>
    <tr>
        <td>834</td>
        <td><a href=players.php?pid=32681&edition=5><span style='color:#00cc00;'>B</span><span
                    style='color:#00bb22;'>R</span><span style='color:#009933;'>E</span><span
                    style='color:#008855;'>N</span><span style='color:#007777;'>T</span><span
                    style='color:#006699;'>_</span><span style='color:#0044aa;'>T</span><span
                    style='color:#0033cc;'>M</span></a></td>
        <td>6</td>
        <td>9245.267</td>
        <td>565.833</td>
    </tr>
    <tr>
        <td>835</td>
        <td><a href=players.php?pid=68264&edition=5>VinchuuuK</a></td>
        <td>6</td>
        <td>9245.280</td>
        <td>566.000</td>
    </tr>
    <tr>
        <td>836</td>
        <td><a href=players.php?pid=65048&edition=5><span style='color:#ffdddd;'>Humfree</span></a></td>
        <td>6</td>
        <td>9246.440</td>
        <td>580.500</td>
    </tr>
    <tr>
        <td>837</td>
        <td><a href=players.php?pid=4328&edition=5><span style='color:#333366;'>A</span><span
                    style='color:#335588;'>i</span><span style='color:#3388aa;'>k</span><span
                    style='color:#33aabb;'>a</span><span style='color:#33dddd;'>n</span><span
                    style='color:#33ffff;'>i</span></a></td>
        <td>6</td>
        <td>9246.747</td>
        <td>584.333</td>
    </tr>
    <tr>
        <td>838</td>
        <td><a href=players.php?pid=56844&edition=5><span style='color:#660000;'>Swa</span><span
                    style='color:#990000;'>nk</span><span style='color:#cc0000;'>Plac</span><span
                    style='color:#ff0000;'>e48</span></a></td>
        <td>6</td>
        <td>9247.120</td>
        <td>589.000</td>
    </tr>
    <tr>
        <td>839</td>
        <td><a href=players.php?pid=67600&edition=5><span style='color:#99cc33;'>&nbsp;</span><span
                    style='color:#779922;'>ﾅ</span><span style='color:#556622;'>h</span><span
                    style='color:#223311;'>e</span><span style='color:#000000;'>B</span><span
                    style='color:#000000;'>l</span><span style='color:#002200;'>a</span><span
                    style='color:#003300;'>c</span><span style='color:#005500;'>К</span><span
                    style='color:#006600;'>_</span></a></td>
        <td>6</td>
        <td>9247.440</td>
        <td>593.000</td>
    </tr>
    <tr>
        <td>840</td>
        <td><a href=players.php?pid=7821&edition=5>Wall-:e:</a></td>
        <td>6</td>
        <td>9247.467</td>
        <td>593.333</td>
    </tr>
    <tr>
        <td>841</td>
        <td><a href=players.php?pid=11071&edition=5>T3V5.</a></td>
        <td>6</td>
        <td>9248.347</td>
        <td>604.333</td>
    </tr>
    <tr>
        <td>842</td>
        <td><a href=players.php?pid=11314&edition=5><span style='color:#aaddee;font-weight:bold;'>Vokster</span></a>
        </td>
        <td>6</td>
        <td>9248.507</td>
        <td>606.333</td>
    </tr>
    <tr>
        <td>843</td>
        <td><a href=players.php?pid=14393&edition=5>sshugo2</a></td>
        <td>6</td>
        <td>9248.640</td>
        <td>608.000</td>
    </tr>
    <tr>
        <td>844</td>
        <td><a href=players.php?pid=31518&edition=5><span
                    style='color:#ff0000;font-style:italic;font-weight:bold;'>P</span><span
                    style='color:#ff8888;font-style:italic;font-weight:bold;'>i</span><span
                    style='color:#ffffff;font-style:italic;font-weight:bold;'>n</span><span
                    style='color:#ffffff;font-style:italic;font-weight:bold;'>d</span><span
                    style='color:#0000ff;font-style:italic;font-weight:bold;'>a</span></a></td>
        <td>6</td>
        <td>9249.040</td>
        <td>613.000</td>
    </tr>
    <tr>
        <td>845</td>
        <td><a href=players.php?pid=67581&edition=5>Izz3Pizz3</a></td>
        <td>6</td>
        <td>9250.320</td>
        <td>629.000</td>
    </tr>
    <tr>
        <td>846</td>
        <td><a href=players.php?pid=66118&edition=5>Opuculus</a></td>
        <td>6</td>
        <td>9250.733</td>
        <td>634.167</td>
    </tr>
    <tr>
        <td>847</td>
        <td><a href=players.php?pid=6491&edition=5><span style='font-style:italic;'>woop&nbsp;</span><span
                    style='color:#ff0000;font-style:italic;'>ツ</span></a></td>
        <td>6</td>
        <td>9251.053</td>
        <td>638.167</td>
    </tr>
    <tr>
        <td>848</td>
        <td><a href=players.php?pid=64030&edition=5>Subwaylvr34</a></td>
        <td>6</td>
        <td>9251.267</td>
        <td>640.833</td>
    </tr>
    <tr>
        <td>849</td>
        <td><a href=players.php?pid=49569&edition=5><span style='color:#0033cc;'>&Theta;</span><span
                    style='color:#4466dd;'>&omega;</span><span style='color:#8899ee;'>&rho;</span><span
                    style='color:#bbccee;'>ά</span><span style='color:#ffffff;'>&sigmaf;</span></a></td>
        <td>6</td>
        <td>9251.653</td>
        <td>645.667</td>
    </tr>
    <tr>
        <td>850</td>
        <td><a href=players.php?pid=50443&edition=5>Mahiya_</a></td>
        <td>6</td>
        <td>9251.920</td>
        <td>649.000</td>
    </tr>
    <tr>
        <td>851</td>
        <td><a href=players.php?pid=57787&edition=5>Amitell74</a></td>
        <td>6</td>
        <td>9253.187</td>
        <td>664.833</td>
    </tr>
    <tr>
        <td>852</td>
        <td><a href=players.php?pid=18873&edition=5>Yenoki</a></td>
        <td>6</td>
        <td>9254.240</td>
        <td>678.000</td>
    </tr>
    <tr>
        <td>853</td>
        <td><a href=players.php?pid=63813&edition=5><span style='color:#ff00ff;'>T</span><span
                    style='color:#dd11ff;'>r</span><span style='color:#cc22ff;'>a</span><span
                    style='color:#bb33ff;'>c</span><span style='color:#aa55ff;'>k</span><span
                    style='color:#9966ff;'>m</span><span style='color:#8877ff;'>a</span><span
                    style='color:#7788ff;'>n</span><span style='color:#6699ff;'>i</span><span
                    style='color:#44aaff;'>a</span><span style='color:#33ccff;'>.</span><span
                    style='color:#22ddff;'>e</span><span style='color:#11eeff;'>x</span><span
                    style='color:#00ffff;'>e</span></a></td>
        <td>6</td>
        <td>9254.813</td>
        <td>685.167</td>
    </tr>
    <tr>
        <td>854</td>
        <td><a href=players.php?pid=49893&edition=5>Mikey2F</a></td>
        <td>6</td>
        <td>9256.200</td>
        <td>702.500</td>
    </tr>
    <tr>
        <td>855</td>
        <td><a href=players.php?pid=62526&edition=5>gorilla:dinkdonk:</a></td>
        <td>6</td>
        <td>9256.573</td>
        <td>707.167</td>
    </tr>
    <tr>
        <td>856</td>
        <td><a href=players.php?pid=68526&edition=5>HashVT</a></td>
        <td>6</td>
        <td>9256.733</td>
        <td>709.167</td>
    </tr>
    <tr>
        <td>857</td>
        <td><a href=players.php?pid=54286&edition=5>El_Bart077</a></td>
        <td>6</td>
        <td>9257.333</td>
        <td>716.667</td>
    </tr>
    <tr>
        <td>858</td>
        <td><a href=players.php?pid=22658&edition=5>lucasjande</a></td>
        <td>6</td>
        <td>9258.933</td>
        <td>736.667</td>
    </tr>
    <tr>
        <td>859</td>
        <td><a href=players.php?pid=58986&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;Trahz</span></a></td>
        <td>6</td>
        <td>9259.000</td>
        <td>737.500</td>
    </tr>
    <tr>
        <td>860</td>
        <td><a href=players.php?pid=52972&edition=5>wangog2149</a></td>
        <td>6</td>
        <td>9259.200</td>
        <td>740.000</td>
    </tr>
    <tr>
        <td>861</td>
        <td><a href=players.php?pid=17182&edition=5>EinfachLucaLive</a></td>
        <td>6</td>
        <td>9260.267</td>
        <td>753.333</td>
    </tr>
    <tr>
        <td>862</td>
        <td><a href=players.php?pid=16567&edition=5><span style='color:#ff6600;'>L</span><span
                    style='color:#dd5500;'>y</span><span style='color:#bb4400;'>s</span><span
                    style='color:#993300;'>d</span><span style='color:#993300;'>e</span><span
                    style='color:#bb4400;'>x</span><span style='color:#dd5500;'>i</span><span
                    style='color:#ff6600;'>c</span></a></td>
        <td>6</td>
        <td>9261.467</td>
        <td>768.333</td>
    </tr>
    <tr>
        <td>863</td>
        <td><a href=players.php?pid=2812&edition=5><span style='color:#9900dd;'>|||</span><span
                    style='color:#ffffff;'>:</span><span style='color:#000000;'>!</span></a></td>
        <td>6</td>
        <td>9261.480</td>
        <td>768.500</td>
    </tr>
    <tr>
        <td>864</td>
        <td><a href=players.php?pid=36738&edition=5><span style='color:#ff9900;'>FLEUR&nbsp;|&nbsp;</span>Sky_Kilian</a>
        </td>
        <td>6</td>
        <td>9261.707</td>
        <td>771.333</td>
    </tr>
    <tr>
        <td>865</td>
        <td><a href=players.php?pid=62401&edition=5><span style='color:#8822bb;'>ゐ</span><span
                    style='color:#9933bb;'>Я</span><span style='color:#9944cc;'>Ə</span><span
                    style='color:#aa55cc;'>ӥ</span><span style='color:#bb77cc;'>Đ</span><span
                    style='color:#bb88cc;'>į</span><span style='color:#cc99dd;'>И</span><span
                    style='color:#ccaadd;'>ん</span><span style='color:#ddbbdd;'>&Phi;</span></a></td>
        <td>6</td>
        <td>9261.840</td>
        <td>773.000</td>
    </tr>
    <tr>
        <td>866</td>
        <td><a href=players.php?pid=55545&edition=5>RoRoRosh</a></td>
        <td>6</td>
        <td>9262.107</td>
        <td>776.333</td>
    </tr>
    <tr>
        <td>867</td>
        <td><a href=players.php?pid=54427&edition=5><span style='color:#00ccff;'>T</span><span
                    style='color:#22ddff;'>e</span><span style='color:#44eeff;'>e</span><span
                    style='color:#66ffff;'>N</span><span style='color:#66ffff;'>a</span><span
                    style='color:#bbffff;'>k</span><span style='color:#ffffff;'>u</span></a></td>
        <td>6</td>
        <td>9263.027</td>
        <td>787.833</td>
    </tr>
    <tr>
        <td>868</td>
        <td><a href=players.php?pid=55904&edition=5>Youdoomedusall6</a></td>
        <td>6</td>
        <td>9263.627</td>
        <td>795.333</td>
    </tr>
    <tr>
        <td>869</td>
        <td><a href=players.php?pid=52998&edition=5>Q-vist</a></td>
        <td>6</td>
        <td>9268.773</td>
        <td>859.667</td>
    </tr>
    <tr>
        <td>870</td>
        <td><a href=players.php?pid=68610&edition=5><span style='color:#aa00ff;'>SƳX</span><span
                    style='color:#ffffff;'>TѺƁƁ</span></a></td>
        <td>6</td>
        <td>9283.013</td>
        <td>1037.667</td>
    </tr>
    <tr>
        <td>871</td>
        <td><a href=players.php?pid=51825&edition=5>Monkboi_</a></td>
        <td>5</td>
        <td>9342.613</td>
        <td>139.200</td>
    </tr>
    <tr>
        <td>872</td>
        <td><a href=players.php?pid=28857&edition=5><span style='color:#00ff00;'>T</span><span
                    style='color:#00ff66;'>r</span><span style='color:#00ff99;'>e</span><span
                    style='color:#66ffcc;'>f</span><span style='color:#33ffff;'>e</span></a></td>
        <td>5</td>
        <td>9345.307</td>
        <td>179.600</td>
    </tr>
    <tr>
        <td>873</td>
        <td><a href=players.php?pid=29978&edition=5>ZNothing69</a></td>
        <td>5</td>
        <td>9346.467</td>
        <td>197.000</td>
    </tr>
    <tr>
        <td>874</td>
        <td><a href=players.php?pid=67548&edition=5>sssam_</a></td>
        <td>5</td>
        <td>9346.760</td>
        <td>201.400</td>
    </tr>
    <tr>
        <td>875</td>
        <td><a href=players.php?pid=51128&edition=5><span style='color:#00ff33;'>Yucki</span><span
                    style='color:#3399ff;'>Guy</span><span style='color:#ffffff;'>_</span><span
                    style='color:#330066;'>TTV</span></a></td>
        <td>5</td>
        <td>9348.000</td>
        <td>220.000</td>
    </tr>
    <tr>
        <td>876</td>
        <td><a href=players.php?pid=53992&edition=5><span style='color:#77ddff;'>s</span><span
                    style='color:#99ccff;'>w</span><span style='color:#aaccff;'>e</span><span
                    style='color:#bbbbff;'>e</span><span style='color:#ccaaff;'>z</span><span
                    style='color:#ee99ff;'>i</span><span style='color:#ff99ff;'>.</span></a></td>
        <td>5</td>
        <td>9348.547</td>
        <td>228.200</td>
    </tr>
    <tr>
        <td>877</td>
        <td><a href=players.php?pid=32196&edition=5>Phlilipp_</a></td>
        <td>5</td>
        <td>9348.773</td>
        <td>231.600</td>
    </tr>
    <tr>
        <td>878</td>
        <td><a href=players.php?pid=29011&edition=5><span style='color:#00ff00;'>Sl1mey</span></a></td>
        <td>5</td>
        <td>9350.480</td>
        <td>257.200</td>
    </tr>
    <tr>
        <td>879</td>
        <td><a href=players.php?pid=34662&edition=5>Justen787</a></td>
        <td>5</td>
        <td>9351.933</td>
        <td>279.000</td>
    </tr>
    <tr>
        <td>880</td>
        <td><a href=players.php?pid=54454&edition=5>SuperMadJoker</a></td>
        <td>5</td>
        <td>9353.120</td>
        <td>296.800</td>
    </tr>
    <tr>
        <td>881</td>
        <td><a href=players.php?pid=67417&edition=5>Probably_Cereal</a></td>
        <td>5</td>
        <td>9353.400</td>
        <td>301.000</td>
    </tr>
    <tr>
        <td>882</td>
        <td><a href=players.php?pid=67295&edition=5>feklfek_</a></td>
        <td>5</td>
        <td>9354.907</td>
        <td>323.600</td>
    </tr>
    <tr>
        <td>883</td>
        <td><a href=players.php?pid=54775&edition=5>key.<span style='color:#ffccff;'>wav&nbsp;</span></a></td>
        <td>5</td>
        <td>9355.573</td>
        <td>333.600</td>
    </tr>
    <tr>
        <td>884</td>
        <td><a href=players.php?pid=67568&edition=5>zelibumba</a></td>
        <td>5</td>
        <td>9355.640</td>
        <td>334.600</td>
    </tr>
    <tr>
        <td>885</td>
        <td><a href=players.php?pid=50677&edition=5>Girafe74</a></td>
        <td>5</td>
        <td>9355.893</td>
        <td>338.400</td>
    </tr>
    <tr>
        <td>886</td>
        <td><a href=players.php?pid=36123&edition=5>Eterni<span style='color:#118811;'>kiwi</span></a></td>
        <td>5</td>
        <td>9356.347</td>
        <td>345.200</td>
    </tr>
    <tr>
        <td>887</td>
        <td><a href=players.php?pid=10816&edition=5>LosGann_TM</a></td>
        <td>5</td>
        <td>9356.560</td>
        <td>348.400</td>
    </tr>
    <tr>
        <td>888</td>
        <td><a href=players.php?pid=54047&edition=5><span style='color:#eeaa44;'>c</span><span
                    style='color:#ffaa77;'>r</span><span style='color:#ffaa99;'>o</span><span
                    style='color:#ffaa99;'>s</span><span style='color:#ddbbcc;'>e</span><span
                    style='color:#bbddff;'>a</span></a></td>
        <td>5</td>
        <td>9356.693</td>
        <td>350.400</td>
    </tr>
    <tr>
        <td>889</td>
        <td><a href=players.php?pid=66269&edition=5><span style='color:#55ddcc;'>C</span><span
                    style='color:#77ccdd;'>h</span><span style='color:#88aadd;'>o</span><span
                    style='color:#aa99dd;'>o</span><span style='color:#bb77dd;'>D</span><span
                    style='color:#cc66dd;'>a</span><span style='color:#ee55dd;'>w</span><span
                    style='color:#ff33ee;'>n</span></a></td>
        <td>5</td>
        <td>9356.907</td>
        <td>353.600</td>
    </tr>
    <tr>
        <td>890</td>
        <td><a href=players.php?pid=52643&edition=5><span style='color:#003366;'>H</span><span
                    style='color:#003399;'>y</span><span style='color:#336699;'>d</span><span
                    style='color:#6699cc;'>r</span><span style='color:#6699ff;'>o</span><span
                    style='color:#003366;'>719</span></a></td>
        <td>5</td>
        <td>9357.560</td>
        <td>363.400</td>
    </tr>
    <tr>
        <td>891</td>
        <td><a href=players.php?pid=67066&edition=5>Cassoule</a></td>
        <td>5</td>
        <td>9357.773</td>
        <td>366.600</td>
    </tr>
    <tr>
        <td>892</td>
        <td><a href=players.php?pid=53854&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='color:#000000;font-style:italic;'>Yoshy</span></a></td>
        <td>5</td>
        <td>9357.787</td>
        <td>366.800</td>
    </tr>
    <tr>
        <td>893</td>
        <td><a href=players.php?pid=66155&edition=5>JustMareng</a></td>
        <td>5</td>
        <td>9358.520</td>
        <td>377.800</td>
    </tr>
    <tr>
        <td>894</td>
        <td><a href=players.php?pid=66196&edition=5>eppjones</a></td>
        <td>5</td>
        <td>9358.747</td>
        <td>381.200</td>
    </tr>
    <tr>
        <td>895</td>
        <td><a href=players.php?pid=65713&edition=5>TheShakenMan</a></td>
        <td>5</td>
        <td>9358.827</td>
        <td>382.400</td>
    </tr>
    <tr>
        <td>896</td>
        <td><a href=players.php?pid=67754&edition=5>Kalamuchata</a></td>
        <td>5</td>
        <td>9359.040</td>
        <td>385.600</td>
    </tr>
    <tr>
        <td>897</td>
        <td><a href=players.php?pid=52442&edition=5>haav_</a></td>
        <td>5</td>
        <td>9359.093</td>
        <td>386.400</td>
    </tr>
    <tr>
        <td>898</td>
        <td><a href=players.php?pid=46251&edition=5>Matrox_e</a></td>
        <td>5</td>
        <td>9359.227</td>
        <td>388.400</td>
    </tr>
    <tr>
        <td>899</td>
        <td><a href=players.php?pid=48811&edition=5>Gawliet</a></td>
        <td>5</td>
        <td>9359.840</td>
        <td>397.600</td>
    </tr>
    <tr>
        <td>900</td>
        <td><a href=players.php?pid=71192&edition=5>D4rklinkz</a></td>
        <td>5</td>
        <td>9360.933</td>
        <td>414.000</td>
    </tr>
    <tr>
        <td>901</td>
        <td><a href=players.php?pid=35440&edition=5><span style='color:#3333ff;'>F</span><span
                    style='color:#4433ff;'>a</span><span style='color:#5544ff;'>y</span><span
                    style='color:#6644ff;'>t</span><span style='color:#7744ff;'>a</span><span
                    style='color:#8855ff;'>l</span><span style='color:#9955ff;'>F</span><span
                    style='color:#aa55ff;'>l</span><span style='color:#bb66ff;'>o</span><span
                    style='color:#cc66ff;'>w</span></a></td>
        <td>5</td>
        <td>9361.147</td>
        <td>417.200</td>
    </tr>
    <tr>
        <td>902</td>
        <td><a href=players.php?pid=69582&edition=5>xReliz</a></td>
        <td>5</td>
        <td>9361.213</td>
        <td>418.200</td>
    </tr>
    <tr>
        <td>903</td>
        <td><a href=players.php?pid=28558&edition=5>Lybero10</a></td>
        <td>5</td>
        <td>9361.427</td>
        <td>421.400</td>
    </tr>
    <tr>
        <td>904</td>
        <td><a href=players.php?pid=27107&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>|&nbsp;Luclyoko</span></a></td>
        <td>5</td>
        <td>9362.227</td>
        <td>433.400</td>
    </tr>
    <tr>
        <td>905</td>
        <td><a href=players.php?pid=51816&edition=5><span style='color:#00ffff;font-weight:bold;'>P</span><span
                    style='color:#22ffff;font-weight:bold;'>o</span><span
                    style='color:#44ffff;font-weight:bold;'>r</span><span
                    style='color:#66ffff;font-weight:bold;'>s</span><span
                    style='color:#88ffff;font-weight:bold;'>t</span><span
                    style='color:#aaffff;font-weight:bold;'>a</span><span
                    style='color:#ccffff;font-weight:bold;'>k</span><span
                    style='color:#ffffff;font-weight:bold;'>o</span></a></td>
        <td>5</td>
        <td>9363.107</td>
        <td>446.600</td>
    </tr>
    <tr>
        <td>906</td>
        <td><a href=players.php?pid=69101&edition=5>DripzV3</a></td>
        <td>5</td>
        <td>9363.320</td>
        <td>449.800</td>
    </tr>
    <tr>
        <td>907</td>
        <td><a href=players.php?pid=9415&edition=5>MopJuice</a></td>
        <td>5</td>
        <td>9363.547</td>
        <td>453.200</td>
    </tr>
    <tr>
        <td>908</td>
        <td><a href=players.php?pid=67633&edition=5>jukkapekka12</a></td>
        <td>5</td>
        <td>9363.747</td>
        <td>456.200</td>
    </tr>
    <tr>
        <td>909</td>
        <td><a href=players.php?pid=40893&edition=5><span style='color:#00cccc;'>_</span><span
                    style='color:#33cc99;'>D</span><span style='color:#66cc66;'>o</span><span
                    style='color:#99cc33;'>c</span><span style='color:#cccc00;'>t</span><span
                    style='color:#cccc00;'>o</span><span style='color:#99cc00;'>r</span><span
                    style='color:#66cc00;'>B</span><span style='color:#33cc00;'>_</span></a></td>
        <td>5</td>
        <td>9363.840</td>
        <td>457.600</td>
    </tr>
    <tr>
        <td>910</td>
        <td><a href=players.php?pid=32018&edition=5><span style='color:#000000;'>N</span><span
                    style='color:#883322;'>e</span><span style='color:#ff6633;'>u</span><span
                    style='color:#ff6633;'>t</span><span style='color:#ff8822;'>y</span><span
                    style='color:#ff9900;'>n</span></a></td>
        <td>5</td>
        <td>9363.947</td>
        <td>459.200</td>
    </tr>
    <tr>
        <td>911</td>
        <td><a href=players.php?pid=51699&edition=5>ToastDonut</a></td>
        <td>5</td>
        <td>9364.053</td>
        <td>460.800</td>
    </tr>
    <tr>
        <td>912</td>
        <td><a href=players.php?pid=67566&edition=5>Jonaeer</a></td>
        <td>5</td>
        <td>9364.520</td>
        <td>467.800</td>
    </tr>
    <tr>
        <td>913</td>
        <td><a href=players.php?pid=68068&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Hecko_Damask</span></a></td>
        <td>5</td>
        <td>9365.080</td>
        <td>476.200</td>
    </tr>
    <tr>
        <td>914</td>
        <td><a href=players.php?pid=7636&edition=5>PainyyyTV</a></td>
        <td>5</td>
        <td>9365.120</td>
        <td>476.800</td>
    </tr>
    <tr>
        <td>915</td>
        <td><a href=players.php?pid=66744&edition=5>dibooTM</a></td>
        <td>5</td>
        <td>9365.240</td>
        <td>478.600</td>
    </tr>
    <tr>
        <td>916</td>
        <td><a href=players.php?pid=6414&edition=5><span style='font-weight:bold;'>tuowƎ</span></a></td>
        <td>5</td>
        <td>9365.520</td>
        <td>482.800</td>
    </tr>
    <tr>
        <td>917</td>
        <td><a href=players.php?pid=66293&edition=5>ertaqui</a></td>
        <td>5</td>
        <td>9365.827</td>
        <td>487.400</td>
    </tr>
    <tr>
        <td>918</td>
        <td><a href=players.php?pid=97&edition=5>scorpiTM</a></td>
        <td>5</td>
        <td>9365.853</td>
        <td>487.800</td>
    </tr>
    <tr>
        <td>919</td>
        <td><a href=players.php?pid=23678&edition=5>Vizser</a></td>
        <td>5</td>
        <td>9366.120</td>
        <td>491.800</td>
    </tr>
    <tr>
        <td>920</td>
        <td><a href=players.php?pid=32482&edition=5>Mercury_Thomas</a></td>
        <td>5</td>
        <td>9366.160</td>
        <td>492.400</td>
    </tr>
    <tr>
        <td>921</td>
        <td><a href=players.php?pid=52423&edition=5>Zmaster1992</a></td>
        <td>5</td>
        <td>9366.640</td>
        <td>499.600</td>
    </tr>
    <tr>
        <td>922</td>
        <td><a href=players.php?pid=36944&edition=5>Txitxolina</a></td>
        <td>5</td>
        <td>9367.320</td>
        <td>509.800</td>
    </tr>
    <tr>
        <td>923</td>
        <td><a href=players.php?pid=12523&edition=5>Steeghos</a></td>
        <td>5</td>
        <td>9367.413</td>
        <td>511.200</td>
    </tr>
    <tr>
        <td>924</td>
        <td><a href=players.php?pid=65499&edition=5><span style='color:#ff0000;'>m</span><span
                    style='color:#ff1100;'>a</span><span style='color:#ff2200;'>x</span><span
                    style='color:#ff3300;'>&nbsp;</span><span style='color:#ff4400;'>:</span><span
                    style='color:#ff5500;'>p</span><span style='color:#ff6600;'>e</span><span
                    style='color:#ff8800;'>e</span><span style='color:#ff9900;'>p</span><span
                    style='color:#ffaa00;'>o</span><span style='color:#ffbb00;'>l</span><span
                    style='color:#ffcc00;'>o</span><span style='color:#ffdd00;'>v</span><span
                    style='color:#ffee00;'>e</span><span style='color:#ffff00;'>:</span></a></td>
        <td>5</td>
        <td>9368.547</td>
        <td>528.200</td>
    </tr>
    <tr>
        <td>925</td>
        <td><a href=players.php?pid=395&edition=5>Croustibat56</a></td>
        <td>5</td>
        <td>9368.893</td>
        <td>533.400</td>
    </tr>
    <tr>
        <td>926</td>
        <td><a href=players.php?pid=662&edition=5>DomBaer</a></td>
        <td>5</td>
        <td>9369.160</td>
        <td>537.400</td>
    </tr>
    <tr>
        <td>927</td>
        <td><a href=players.php?pid=25806&edition=5>MozaTM</a></td>
        <td>5</td>
        <td>9369.813</td>
        <td>547.200</td>
    </tr>
    <tr>
        <td>928</td>
        <td><a href=players.php?pid=47951&edition=5>specrte</a></td>
        <td>5</td>
        <td>9370.080</td>
        <td>551.200</td>
    </tr>
    <tr>
        <td>929</td>
        <td><a href=players.php?pid=11374&edition=5>SecretBuffalo</a></td>
        <td>5</td>
        <td>9370.427</td>
        <td>556.400</td>
    </tr>
    <tr>
        <td>930</td>
        <td><a href=players.php?pid=68418&edition=5>Spffyy</a></td>
        <td>5</td>
        <td>9370.667</td>
        <td>560.000</td>
    </tr>
    <tr>
        <td>931</td>
        <td><a href=players.php?pid=50342&edition=5>iducke</a></td>
        <td>5</td>
        <td>9370.733</td>
        <td>561.000</td>
    </tr>
    <tr>
        <td>932</td>
        <td><a href=players.php?pid=24319&edition=5><span style='color:#333300;'>P</span><span
                    style='color:#555500;'>A</span><span style='color:#666600;'>A</span><span
                    style='color:#666600;'>Z</span><span style='color:#666633;'>T</span><span
                    style='color:#666666;'>入</span></a></td>
        <td>5</td>
        <td>9370.880</td>
        <td>563.200</td>
    </tr>
    <tr>
        <td>933</td>
        <td><a href=players.php?pid=68633&edition=5>Lu_rkE</a></td>
        <td>5</td>
        <td>9371.360</td>
        <td>570.400</td>
    </tr>
    <tr>
        <td>934</td>
        <td><a href=players.php?pid=34787&edition=5>Mr.Jazavac.TB</a></td>
        <td>5</td>
        <td>9371.453</td>
        <td>571.800</td>
    </tr>
    <tr>
        <td>935</td>
        <td><a href=players.php?pid=54223&edition=5>Octatwo</a></td>
        <td>5</td>
        <td>9372.440</td>
        <td>586.600</td>
    </tr>
    <tr>
        <td>936</td>
        <td><a href=players.php?pid=38122&edition=5>Wicky88</a></td>
        <td>5</td>
        <td>9372.800</td>
        <td>592.000</td>
    </tr>
    <tr>
        <td>937</td>
        <td><a href=players.php?pid=35500&edition=5><span style='color:#cc6600;'>&nbsp;marshman314</span></a></td>
        <td>5</td>
        <td>9373.053</td>
        <td>595.800</td>
    </tr>
    <tr>
        <td>938</td>
        <td><a href=players.php?pid=69467&edition=5>Jakalus</a></td>
        <td>5</td>
        <td>9373.560</td>
        <td>603.400</td>
    </tr>
    <tr>
        <td>939</td>
        <td><a href=players.php?pid=6449&edition=5><span style='color:#ff7755;'>X</span><span
                    style='color:#dd9944;'>y</span><span style='color:#ccaa33;'>a</span><span
                    style='color:#aacc22;'>g</span><span style='color:#99dd11;'>o</span><span
                    style='color:#77ff00;'>n</span></a></td>
        <td>5</td>
        <td>9374.387</td>
        <td>615.800</td>
    </tr>
    <tr>
        <td>940</td>
        <td><a href=players.php?pid=67772&edition=5><span style='color:#ff0000;'>じ</span><span
                    style='color:#ff1100;'>ά</span><span style='color:#ff2200;'>ท</span><span
                    style='color:#ff3300;'>G</span><span style='color:#ff5500;'>Ė</span><span
                    style='color:#ff6600;'>&Pi;</span><span style='color:#ff7700;'>丹</span><span
                    style='color:#ff8800;'>ņ</span><span style='color:#ff9900;'>ภ</span><span
                    style='color:#ffaa00;'>.</span><span style='color:#ffcc00;'>_</span><span
                    style='color:#ffdd00;'>.</span><span style='color:#ffee00;'>ﾋ</span><span
                    style='color:#ffff00;'>m</span></a></td>
        <td>5</td>
        <td>9374.520</td>
        <td>617.800</td>
    </tr>
    <tr>
        <td>941</td>
        <td><a href=players.php?pid=66378&edition=5>iDevy</a></td>
        <td>5</td>
        <td>9374.640</td>
        <td>619.600</td>
    </tr>
    <tr>
        <td>942</td>
        <td><a href=players.php?pid=67849&edition=5>cruplet</a></td>
        <td>5</td>
        <td>9374.747</td>
        <td>621.200</td>
    </tr>
    <tr>
        <td>943</td>
        <td><a href=players.php?pid=52277&edition=5>W1llis.</a></td>
        <td>5</td>
        <td>9375.080</td>
        <td>626.200</td>
    </tr>
    <tr>
        <td>944</td>
        <td><a href=players.php?pid=44686&edition=5>Wi1s0ne</a></td>
        <td>5</td>
        <td>9375.467</td>
        <td>632.000</td>
    </tr>
    <tr>
        <td>945</td>
        <td><a href=players.php?pid=32627&edition=5>sjafo</a></td>
        <td>5</td>
        <td>9375.920</td>
        <td>638.800</td>
    </tr>
    <tr>
        <td>946</td>
        <td><a href=players.php?pid=68685&edition=5>BlueBarian</a></td>
        <td>5</td>
        <td>9375.960</td>
        <td>639.400</td>
    </tr>
    <tr>
        <td>947</td>
        <td><a href=players.php?pid=64307&edition=5>Falckiee2nd</a></td>
        <td>5</td>
        <td>9375.987</td>
        <td>639.800</td>
    </tr>
    <tr>
        <td>948</td>
        <td><a href=players.php?pid=22426&edition=5>LolloTheMad</a></td>
        <td>5</td>
        <td>9376.107</td>
        <td>641.600</td>
    </tr>
    <tr>
        <td>949</td>
        <td><a href=players.php?pid=32343&edition=5>meowloa</a></td>
        <td>5</td>
        <td>9376.147</td>
        <td>642.200</td>
    </tr>
    <tr>
        <td>950</td>
        <td><a href=players.php?pid=66&edition=5>KilLErDaV24</a></td>
        <td>5</td>
        <td>9376.560</td>
        <td>648.400</td>
    </tr>
    <tr>
        <td>951</td>
        <td><a href=players.php?pid=25126&edition=5>H2SO4_TM</a></td>
        <td>5</td>
        <td>9376.640</td>
        <td>649.600</td>
    </tr>
    <tr>
        <td>952</td>
        <td><a href=players.php?pid=29625&edition=5><span style='color:#330000;'>T</span><span
                    style='color:#553311;'>I</span><span style='color:#775511;'>G</span><span
                    style='color:#998822;'>:e:</span><span style='color:#ffff33;'>R</span><span
                    style='color:#ffff33;'>&nbsp;</span><span style='color:#ffcc22;'>M</span><span
                    style='color:#ff9922;'>A</span><span style='color:#ff6611;'>F</span><span
                    style='color:#ff3311;'>I</span><span style='color:#ff0000;'>A</span></a></td>
        <td>5</td>
        <td>9376.933</td>
        <td>654.000</td>
    </tr>
    <tr>
        <td>953</td>
        <td><a href=players.php?pid=32020&edition=5>ironhead39</a></td>
        <td>5</td>
        <td>9377.147</td>
        <td>657.200</td>
    </tr>
    <tr>
        <td>954</td>
        <td><a href=players.php?pid=66065&edition=5>vorticepen</a></td>
        <td>5</td>
        <td>9377.187</td>
        <td>657.800</td>
    </tr>
    <tr>
        <td>955</td>
        <td><a href=players.php?pid=66478&edition=5>goomblor</a></td>
        <td>5</td>
        <td>9377.347</td>
        <td>660.200</td>
    </tr>
    <tr>
        <td>956</td>
        <td><a href=players.php?pid=69570&edition=5>acr1ter</a></td>
        <td>5</td>
        <td>9378.080</td>
        <td>671.200</td>
    </tr>
    <tr>
        <td>957</td>
        <td><a href=players.php?pid=53245&edition=5>Dippaasunballz</a></td>
        <td>5</td>
        <td>9378.107</td>
        <td>671.600</td>
    </tr>
    <tr>
        <td>958</td>
        <td><a href=players.php?pid=69177&edition=5><span style='color:#00aaff;'>Niam</span><span
                    style='color:#00ccff;'>2008</span></a></td>
        <td>5</td>
        <td>9378.120</td>
        <td>671.800</td>
    </tr>
    <tr>
        <td>959</td>
        <td><a href=players.php?pid=24506&edition=5><span
                    style='color:#00ffff;font-weight:bold;'>PseudoDragon</span></a></td>
        <td>5</td>
        <td>9378.867</td>
        <td>683.000</td>
    </tr>
    <tr>
        <td>960</td>
        <td><a href=players.php?pid=34450&edition=5>ratatatosh</a></td>
        <td>5</td>
        <td>9379.147</td>
        <td>687.200</td>
    </tr>
    <tr>
        <td>961</td>
        <td><a href=players.php?pid=66417&edition=5><span style='color:#00ffff;'>Ƙristǎlisฬ</span></a></td>
        <td>5</td>
        <td>9379.973</td>
        <td>699.600</td>
    </tr>
    <tr>
        <td>962</td>
        <td><a href=players.php?pid=15105&edition=5>AncientSt0rm</a></td>
        <td>5</td>
        <td>9380.200</td>
        <td>703.000</td>
    </tr>
    <tr>
        <td>963</td>
        <td><a href=players.php?pid=53788&edition=5>IsstoNie</a></td>
        <td>5</td>
        <td>9380.573</td>
        <td>708.600</td>
    </tr>
    <tr>
        <td>964</td>
        <td><a href=players.php?pid=32459&edition=5>DaPlumboy</a></td>
        <td>5</td>
        <td>9380.907</td>
        <td>713.600</td>
    </tr>
    <tr>
        <td>965</td>
        <td><a href=players.php?pid=68057&edition=5>WATAAAAA.</a></td>
        <td>5</td>
        <td>9381.280</td>
        <td>719.200</td>
    </tr>
    <tr>
        <td>966</td>
        <td><a href=players.php?pid=6834&edition=5>DepBastos</a></td>
        <td>5</td>
        <td>9381.987</td>
        <td>729.800</td>
    </tr>
    <tr>
        <td>967</td>
        <td><a href=players.php?pid=32671&edition=5>b<span
                    style='color:#ff00ff;font-style:italic;'>&nbsp;POULE&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;Linsquey</span></a></td>
        <td>5</td>
        <td>9382.213</td>
        <td>733.200</td>
    </tr>
    <tr>
        <td>968</td>
        <td><a href=players.php?pid=18577&edition=5><span style='color:#009900;'>D</span><span
                    style='color:#22aa22;'>E</span><span style='color:#33bb33;'>G</span><span
                    style='color:#55bb55;'>S</span><span style='color:#66cc66;'>&nbsp;</span><span
                    style='color:#ffffff;'>Chayann23TM</span></a></td>
        <td>5</td>
        <td>9382.320</td>
        <td>734.800</td>
    </tr>
    <tr>
        <td>969</td>
        <td><a href=players.php?pid=17849&edition=5>Nuclearrr.</a></td>
        <td>5</td>
        <td>9382.413</td>
        <td>736.200</td>
    </tr>
    <tr>
        <td>970</td>
        <td><a href=players.php?pid=57289&edition=5>zakiwaki</a></td>
        <td>5</td>
        <td>9382.720</td>
        <td>740.800</td>
    </tr>
    <tr>
        <td>971</td>
        <td><a href=players.php?pid=6808&edition=5>BaguetteTM</a></td>
        <td>5</td>
        <td>9382.800</td>
        <td>742.000</td>
    </tr>
    <tr>
        <td>972</td>
        <td><a href=players.php?pid=8158&edition=5><span style='color:#6666ff;'>J</span><span
                    style='color:#7777ff;'>a</span><span style='color:#8888ff;'>i</span><span
                    style='color:#9999ff;'>o</span></a></td>
        <td>5</td>
        <td>9382.920</td>
        <td>743.800</td>
    </tr>
    <tr>
        <td>973</td>
        <td><a href=players.php?pid=66340&edition=5>Filip5_cz</a></td>
        <td>5</td>
        <td>9382.933</td>
        <td>744.000</td>
    </tr>
    <tr>
        <td>974</td>
        <td><a href=players.php?pid=69283&edition=5>Ornityr</a></td>
        <td>5</td>
        <td>9384.347</td>
        <td>765.200</td>
    </tr>
    <tr>
        <td>975</td>
        <td><a href=players.php?pid=13514&edition=5>Ryutzu</a></td>
        <td>5</td>
        <td>9387.800</td>
        <td>817.000</td>
    </tr>
    <tr>
        <td>976</td>
        <td><a href=players.php?pid=70722&edition=5>DEVINURDOG</a></td>
        <td>5</td>
        <td>9387.987</td>
        <td>819.800</td>
    </tr>
    <tr>
        <td>977</td>
        <td><a href=players.php?pid=69497&edition=5>SiriusBull</a></td>
        <td>5</td>
        <td>9388.813</td>
        <td>832.200</td>
    </tr>
    <tr>
        <td>978</td>
        <td><a href=players.php?pid=33642&edition=5>Stan_12</a></td>
        <td>5</td>
        <td>9389.173</td>
        <td>837.600</td>
    </tr>
    <tr>
        <td>979</td>
        <td><a href=players.php?pid=31431&edition=5><span style='color:#33ff00;'>ғ</span><span
                    style='color:#33dd00;'>Ŀ</span>0<span style='color:#339900;'>ѿ</span></a></td>
        <td>5</td>
        <td>9389.253</td>
        <td>838.800</td>
    </tr>
    <tr>
        <td>980</td>
        <td><a href=players.php?pid=6899&edition=5>AllenBomba</a></td>
        <td>5</td>
        <td>9389.413</td>
        <td>841.200</td>
    </tr>
    <tr>
        <td>981</td>
        <td><a href=players.php?pid=32147&edition=5>tealemc</a></td>
        <td>5</td>
        <td>9389.840</td>
        <td>847.600</td>
    </tr>
    <tr>
        <td>982</td>
        <td><a href=players.php?pid=69295&edition=5>Benedict.4PF</a></td>
        <td>5</td>
        <td>9391.067</td>
        <td>866.000</td>
    </tr>
    <tr>
        <td>983</td>
        <td><a href=players.php?pid=66821&edition=5>Mr.Mean23o</a></td>
        <td>5</td>
        <td>9391.320</td>
        <td>869.800</td>
    </tr>
    <tr>
        <td>984</td>
        <td><a href=players.php?pid=54287&edition=5>Div_Nic</a></td>
        <td>5</td>
        <td>9394.240</td>
        <td>913.600</td>
    </tr>
    <tr>
        <td>985</td>
        <td><a href=players.php?pid=57296&edition=5><span style='color:#9900dd;'>L</span><span
                    style='color:#7722dd;'>o</span><span style='color:#5544ee;'>m</span><span
                    style='color:#4477ee;'>i</span><span style='color:#2299ff;'>i</span><span
                    style='color:#00bbff;'>g</span></a></td>
        <td>5</td>
        <td>9394.253</td>
        <td>913.800</td>
    </tr>
    <tr>
        <td>986</td>
        <td><a href=players.php?pid=32304&edition=5>Bang</a></td>
        <td>5</td>
        <td>9394.387</td>
        <td>915.800</td>
    </tr>
    <tr>
        <td>987</td>
        <td><a href=players.php?pid=38847&edition=5>t3kneeq</a></td>
        <td>5</td>
        <td>9398.240</td>
        <td>973.600</td>
    </tr>
    <tr>
        <td>988</td>
        <td><a href=players.php?pid=55695&edition=5><span style='color:#00ffff;'>Random&nbsp;</span><span
                    style='color:#0000ff;'>Penguin</span></a></td>
        <td>4</td>
        <td>9472.480</td>
        <td>109.000</td>
    </tr>
    <tr>
        <td>989</td>
        <td><a href=players.php?pid=8001&edition=5>baiwack</a></td>
        <td>4</td>
        <td>9476.427</td>
        <td>183.000</td>
    </tr>
    <tr>
        <td>990</td>
        <td><a href=players.php?pid=13118&edition=5><span style='color:#ff0000;'>Un</span><span
                    style='color:#ff3333;'>iF&nbsp;</span><span style='color:#eeeeee;'>Da</span><span
                    style='color:#cccccc;'>mo</span><span style='color:#aaaaaa;'>loss</span></a></td>
        <td>4</td>
        <td>9476.787</td>
        <td>189.750</td>
    </tr>
    <tr>
        <td>991</td>
        <td><a href=players.php?pid=18877&edition=5>Boarito</a></td>
        <td>4</td>
        <td>9476.893</td>
        <td>191.750</td>
    </tr>
    <tr>
        <td>992</td>
        <td><a href=players.php?pid=7118&edition=5><span style='color:#0066ff;font-weight:bold;'>M</span><span
                    style='color:#0099ff;font-weight:bold;'>e</span><span
                    style='color:#00bbff;font-weight:bold;'>r</span><span
                    style='color:#00ccff;font-weight:bold;'>y</span></a></td>
        <td>4</td>
        <td>9477.947</td>
        <td>211.500</td>
    </tr>
    <tr>
        <td>993</td>
        <td><a href=players.php?pid=66774&edition=5>SanguineMyBruh</a></td>
        <td>4</td>
        <td>9479.373</td>
        <td>238.250</td>
    </tr>
    <tr>
        <td>994</td>
        <td><a href=players.php?pid=6244&edition=5><span style='color:#3366cc;'>s</span><span
                    style='color:#5588aa;'>w</span><span style='color:#88aa77;'>i</span><span
                    style='color:#aabb55;'>t</span><span style='color:#dddd22;'>c</span><span
                    style='color:#ffff00;'>ん</span></a></td>
        <td>4</td>
        <td>9479.427</td>
        <td>239.250</td>
    </tr>
    <tr>
        <td>995</td>
        <td><a href=players.php?pid=20212&edition=5>Luukasa123</a></td>
        <td>4</td>
        <td>9479.693</td>
        <td>244.250</td>
    </tr>
    <tr>
        <td>996</td>
        <td><a href=players.php?pid=411&edition=5>Hazardu.</a></td>
        <td>4</td>
        <td>9480.573</td>
        <td>260.750</td>
    </tr>
    <tr>
        <td>997</td>
        <td><a href=players.php?pid=61567&edition=5>fauli_balulu</a></td>
        <td>4</td>
        <td>9481.973</td>
        <td>287.000</td>
    </tr>
    <tr>
        <td>998</td>
        <td><a href=players.php?pid=65653&edition=5>popreca</a></td>
        <td>4</td>
        <td>9482.280</td>
        <td>292.750</td>
    </tr>
    <tr>
        <td>999</td>
        <td><a href=players.php?pid=66147&edition=5>Calcaire.</a></td>
        <td>4</td>
        <td>9483.853</td>
        <td>322.250</td>
    </tr>
    <tr>
        <td>1000</td>
        <td><a href=players.php?pid=69044&edition=5>Alkift</a></td>
        <td>4</td>
        <td>9483.893</td>
        <td>323.000</td>
    </tr>
    <tr>
        <td>1001</td>
        <td><a href=players.php?pid=28538&edition=5><span style='color:#ffffff;font-style:italic;'>shen</span></a></td>
        <td>4</td>
        <td>9484.320</td>
        <td>331.000</td>
    </tr>
    <tr>
        <td>1002</td>
        <td><a href=players.php?pid=37203&edition=5>KeyanB_</a></td>
        <td>4</td>
        <td>9484.320</td>
        <td>331.000</td>
    </tr>
    <tr>
        <td>1003</td>
        <td><a href=players.php?pid=53381&edition=5>AnitaaMaxWynn-</a></td>
        <td>4</td>
        <td>9484.373</td>
        <td>332.000</td>
    </tr>
    <tr>
        <td>1004</td>
        <td><a href=players.php?pid=32252&edition=5><span style='color:#1133bb;'>Ҝ</span><span
                    style='color:#1122aa;'>&chi;</span><span style='color:#112299;'>ұ</span><span
                    style='color:#001177;'>&lambda;</span><span style='color:#000066;'>ҟ</span></a></td>
        <td>4</td>
        <td>9484.440</td>
        <td>333.250</td>
    </tr>
    <tr>
        <td>1005</td>
        <td><a href=players.php?pid=38589&edition=5><span style='color:#33cccc;'>V</span><span
                    style='color:#5599cc;'>〶</span><span style='color:#6666cc;'>N</span><span
                    style='color:#8833cc;'>į</span><span style='color:#9900cc;'>ת</span><span
                    style='color:#9900cc;'>j</span><span style='color:#7711cc;'>ă</span><span
                    style='color:#5522cc;'>1</span>0</a></td>
        <td>4</td>
        <td>9484.453</td>
        <td>333.500</td>
    </tr>
    <tr>
        <td>1006</td>
        <td><a href=players.php?pid=6905&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>Zaco</span></a></td>
        <td>4</td>
        <td>9484.600</td>
        <td>336.250</td>
    </tr>
    <tr>
        <td>1007</td>
        <td><a href=players.php?pid=63689&edition=5>NuttyNerves</a></td>
        <td>4</td>
        <td>9485.267</td>
        <td>348.750</td>
    </tr>
    <tr>
        <td>1008</td>
        <td><a href=players.php?pid=32828&edition=5>Koekoek2006</a></td>
        <td>4</td>
        <td>9486.093</td>
        <td>364.250</td>
    </tr>
    <tr>
        <td>1009</td>
        <td><a href=players.php?pid=64587&edition=5>Atarexy</a></td>
        <td>4</td>
        <td>9486.560</td>
        <td>373.000</td>
    </tr>
    <tr>
        <td>1010</td>
        <td><a href=players.php?pid=52478&edition=5>Dadologic</a></td>
        <td>4</td>
        <td>9487.320</td>
        <td>387.250</td>
    </tr>
    <tr>
        <td>1011</td>
        <td><a href=players.php?pid=16081&edition=5>StrawHatTM</a></td>
        <td>4</td>
        <td>9487.680</td>
        <td>394.000</td>
    </tr>
    <tr>
        <td>1012</td>
        <td><a href=players.php?pid=11307&edition=5><span style='color:#0033cc;font-style:italic;'>C</span><span
                    style='color:#5577dd;font-style:italic;'>l</span><span
                    style='color:#aabbee;font-style:italic;'>e</span><span
                    style='color:#ffffff;font-style:italic;'>f</span><span
                    style='color:#ffffff;font-style:italic;'>d</span><span
                    style='color:#ccbbff;font-style:italic;'>e</span><span
                    style='color:#9977ff;font-style:italic;'>1</span><span
                    style='color:#6633ff;font-style:italic;'>2</span></a></td>
        <td>4</td>
        <td>9487.880</td>
        <td>397.750</td>
    </tr>
    <tr>
        <td>1013</td>
        <td><a href=players.php?pid=33417&edition=5>MomoWiggles</a></td>
        <td>4</td>
        <td>9488.120</td>
        <td>402.250</td>
    </tr>
    <tr>
        <td>1014</td>
        <td><a href=players.php?pid=55660&edition=5><span style='color:#00ffff;'>б</span><span
                    style='color:#22ffbb;'>ﾋ</span><span style='color:#44ff77;'>ң</span><span
                    style='color:#66ff33;'>л</span><span style='color:#66ff33;'>&pi;</span><span
                    style='color:#bbff22;'>エ</span><span style='color:#ffff00;'>ѷ</span></a></td>
        <td>4</td>
        <td>9488.413</td>
        <td>407.750</td>
    </tr>
    <tr>
        <td>1015</td>
        <td><a href=players.php?pid=54855&edition=5>drako533</a></td>
        <td>4</td>
        <td>9488.827</td>
        <td>415.500</td>
    </tr>
    <tr>
        <td>1016</td>
        <td><a href=players.php?pid=57146&edition=5>N0xif</a></td>
        <td>4</td>
        <td>9488.920</td>
        <td>417.250</td>
    </tr>
    <tr>
        <td>1017</td>
        <td><a href=players.php?pid=70388&edition=5>Gonnethu</a></td>
        <td>4</td>
        <td>9489.093</td>
        <td>420.500</td>
    </tr>
    <tr>
        <td>1018</td>
        <td><a href=players.php?pid=30081&edition=5><span style='color:#ccff00;'>D</span><span
                    style='color:#99dd44;'>a</span><span style='color:#66bb88;'>z</span><span
                    style='color:#3388bb;'>e</span><span style='color:#0066ff;'>d</span></a></td>
        <td>4</td>
        <td>9489.293</td>
        <td>424.250</td>
    </tr>
    <tr>
        <td>1019</td>
        <td><a href=players.php?pid=49305&edition=5><span style='color:#ff66ff;'>Remori</span><span
                    style='color:#55ccff;'>Desu</span></a></td>
        <td>4</td>
        <td>9489.613</td>
        <td>430.250</td>
    </tr>
    <tr>
        <td>1020</td>
        <td><a href=players.php?pid=31592&edition=5>Slashasher</a></td>
        <td>4</td>
        <td>9490.040</td>
        <td>438.250</td>
    </tr>
    <tr>
        <td>1021</td>
        <td><a href=players.php?pid=66693&edition=5>skarbels00</a></td>
        <td>4</td>
        <td>9490.547</td>
        <td>447.750</td>
    </tr>
    <tr>
        <td>1022</td>
        <td><a href=players.php?pid=66219&edition=5>Nirfu-</a></td>
        <td>4</td>
        <td>9490.720</td>
        <td>451.000</td>
    </tr>
    <tr>
        <td>1023</td>
        <td><a href=players.php?pid=65423&edition=5>ejjy405</a></td>
        <td>4</td>
        <td>9491.120</td>
        <td>458.500</td>
    </tr>
    <tr>
        <td>1024</td>
        <td><a href=players.php?pid=54226&edition=5><span style='color:#000000;'>F</span><span
                    style='color:#550000;'>i</span><span style='color:#aa0000;'>r</span><span
                    style='color:#ff0000;'>e</span><span style='color:#ff0000;'>L</span><span
                    style='color:#aa0000;'>o</span><span style='color:#550000;'>r</span><span
                    style='color:#000000;'>d</span></a></td>
        <td>4</td>
        <td>9491.213</td>
        <td>460.250</td>
    </tr>
    <tr>
        <td>1025</td>
        <td><a href=players.php?pid=47151&edition=5><span style='color:#0000cc;font-weight:bold;'>M</span><span
                    style='color:#1133dd;font-weight:bold;'>a</span><span
                    style='color:#1166dd;font-weight:bold;'>r</span><span
                    style='color:#2299ee;font-weight:bold;'>t</span><span
                    style='color:#22ccee;font-weight:bold;'>i</span><span
                    style='color:#33ffff;font-weight:bold;'>j</span><span
                    style='color:#33ffff;font-weight:bold;'>n</span><span
                    style='color:#22bbee;font-weight:bold;'>_</span><span
                    style='color:#2288ee;font-weight:bold;'>W</span><span
                    style='color:#1144dd;font-weight:bold;'>D</span><span
                    style='color:#0000cc;font-weight:bold;'>B</span></a></td>
        <td>4</td>
        <td>9491.240</td>
        <td>460.750</td>
    </tr>
    <tr>
        <td>1026</td>
        <td><a href=players.php?pid=28072&edition=5><span style='color:#ff9900;'>P</span><span
                    style='color:#ffbb22;'>a</span><span style='color:#ffcc33;'>n</span><span
                    style='color:#ffee55;'>c</span><span style='color:#ffff66;'>a</span><span
                    style='color:#ffff66;'>k</span><span style='color:#ffdd44;'>e</span><span
                    style='color:#ffbb22;'>s</span><span style='color:#ffffff;'>ツ</span></a></td>
        <td>4</td>
        <td>9491.493</td>
        <td>465.500</td>
    </tr>
    <tr>
        <td>1027</td>
        <td><a href=players.php?pid=15174&edition=5>:WICKED:&nbsp;Cry0ss&nbsp;:WICKED:</a></td>
        <td>4</td>
        <td>9491.587</td>
        <td>467.250</td>
    </tr>
    <tr>
        <td>1028</td>
        <td><a href=players.php?pid=9080&edition=5>Joudy11</a></td>
        <td>4</td>
        <td>9491.667</td>
        <td>468.750</td>
    </tr>
    <tr>
        <td>1029</td>
        <td><a href=players.php?pid=58880&edition=5>EmilVallda</a></td>
        <td>4</td>
        <td>9491.920</td>
        <td>473.500</td>
    </tr>
    <tr>
        <td>1030</td>
        <td><a href=players.php?pid=1674&edition=5><span style='color:#ee1166;'>Tacc</span><span
                    style='color:#ffffff;'>nien</span></a></td>
        <td>4</td>
        <td>9492.627</td>
        <td>486.750</td>
    </tr>
    <tr>
        <td>1031</td>
        <td><a href=players.php?pid=30153&edition=5>Noby..</a></td>
        <td>4</td>
        <td>9492.627</td>
        <td>486.750</td>
    </tr>
    <tr>
        <td>1032</td>
        <td><a href=players.php?pid=66159&edition=5>Fiffous</a></td>
        <td>4</td>
        <td>9493.107</td>
        <td>495.750</td>
    </tr>
    <tr>
        <td>1033</td>
        <td><a href=players.php?pid=15832&edition=5>taylantm</a></td>
        <td>4</td>
        <td>9493.200</td>
        <td>497.500</td>
    </tr>
    <tr>
        <td>1034</td>
        <td><a href=players.php?pid=24&edition=5><span style='color:#227700;'>B</span><span
                    style='color:#227711;'>r</span><span style='color:#226633;'>e</span><span
                    style='color:#116644;'>a</span><span style='color:#116655;'>k</span><span
                    style='color:#115566;'>b</span><span style='color:#115577;'>e</span><span
                    style='color:#004488;'>a</span><span style='color:#004499;'>t</span><span
                    style='color:#0044bb;'>z</span></a></td>
        <td>4</td>
        <td>9494.267</td>
        <td>517.500</td>
    </tr>
    <tr>
        <td>1035</td>
        <td><a href=players.php?pid=24835&edition=5>The_Assist</a></td>
        <td>4</td>
        <td>9494.333</td>
        <td>518.750</td>
    </tr>
    <tr>
        <td>1036</td>
        <td><a href=players.php?pid=66691&edition=5>Kerze.</a></td>
        <td>4</td>
        <td>9495.440</td>
        <td>539.500</td>
    </tr>
    <tr>
        <td>1037</td>
        <td><a href=players.php?pid=65852&edition=5>COT&nbsp;|&nbsp;Sachatte</a></td>
        <td>4</td>
        <td>9495.520</td>
        <td>541.000</td>
    </tr>
    <tr>
        <td>1038</td>
        <td><a href=players.php?pid=753&edition=5><span style='color:#00ffcc;'>S</span><span
                    style='color:#11ffcc;'>BV</span><span style='color:#22ffcc;'>il</span><span
                    style='color:#33ffcc;'>le</span></a></td>
        <td>4</td>
        <td>9495.893</td>
        <td>548.000</td>
    </tr>
    <tr>
        <td>1039</td>
        <td><a href=players.php?pid=65958&edition=5>Mellismacka</a></td>
        <td>4</td>
        <td>9495.893</td>
        <td>548.000</td>
    </tr>
    <tr>
        <td>1040</td>
        <td><a href=players.php?pid=40996&edition=5>Adrianlol1</a></td>
        <td>4</td>
        <td>9495.920</td>
        <td>548.500</td>
    </tr>
    <tr>
        <td>1041</td>
        <td><a href=players.php?pid=66940&edition=5>Moriarti_TM</a></td>
        <td>4</td>
        <td>9496.240</td>
        <td>554.500</td>
    </tr>
    <tr>
        <td>1042</td>
        <td><a href=players.php?pid=68095&edition=5>HEMAN:ben:</a></td>
        <td>4</td>
        <td>9496.293</td>
        <td>555.500</td>
    </tr>
    <tr>
        <td>1043</td>
        <td><a href=players.php?pid=15072&edition=5><span style='color:#000000;'>♤&nbsp;</span><span
                    style='color:#aa66ff;'>เ</span><span style='color:#cc99ff;'>ה</span><span
                    style='color:#ddccff;'>v</span><span style='color:#ffffff;'>4</span><span
                    style='color:#ffffcc;'>l</span><span style='color:#ffff99;'>เ</span><span
                    style='color:#ffff66;'>đ</span></a></td>
        <td>4</td>
        <td>9496.347</td>
        <td>556.500</td>
    </tr>
    <tr>
        <td>1044</td>
        <td><a href=players.php?pid=66344&edition=5><span style='color:#dd0077;'>||</span><span
                    style='color:#993399;'>|</span><span style='color:#0033aa;'>||&nbsp;</span><span
                    style='color:#000000;'>Dr.</span><span style='color:#339933;'>Jiggle</span><span
                    style='color:#ffffcc;'>Bones</span></a></td>
        <td>4</td>
        <td>9496.520</td>
        <td>559.750</td>
    </tr>
    <tr>
        <td>1045</td>
        <td><a href=players.php?pid=66495&edition=5>tekrama777</a></td>
        <td>4</td>
        <td>9496.613</td>
        <td>561.500</td>
    </tr>
    <tr>
        <td>1046</td>
        <td><a href=players.php?pid=55544&edition=5>Takeooooo</a></td>
        <td>4</td>
        <td>9497.027</td>
        <td>569.250</td>
    </tr>
    <tr>
        <td>1047</td>
        <td><a href=players.php?pid=35382&edition=5>Pnisj</a></td>
        <td>4</td>
        <td>9497.307</td>
        <td>574.500</td>
    </tr>
    <tr>
        <td>1048</td>
        <td><a href=players.php?pid=65895&edition=5>le_Nard34</a></td>
        <td>4</td>
        <td>9497.627</td>
        <td>580.500</td>
    </tr>
    <tr>
        <td>1049</td>
        <td><a href=players.php?pid=67691&edition=5>TitoNhembre</a></td>
        <td>4</td>
        <td>9497.813</td>
        <td>584.000</td>
    </tr>
    <tr>
        <td>1050</td>
        <td><a href=players.php?pid=54192&edition=5>Urmie</a></td>
        <td>4</td>
        <td>9497.813</td>
        <td>584.000</td>
    </tr>
    <tr>
        <td>1051</td>
        <td><a href=players.php?pid=41534&edition=5>Robofishone</a></td>
        <td>4</td>
        <td>9497.907</td>
        <td>585.750</td>
    </tr>
    <tr>
        <td>1052</td>
        <td><a href=players.php?pid=49962&edition=5>Nimdar.</a></td>
        <td>4</td>
        <td>9498.133</td>
        <td>590.000</td>
    </tr>
    <tr>
        <td>1053</td>
        <td><a href=players.php?pid=60807&edition=5>williamboodoo</a></td>
        <td>4</td>
        <td>9498.173</td>
        <td>590.750</td>
    </tr>
    <tr>
        <td>1054</td>
        <td><a href=players.php?pid=69113&edition=5>Nakyu</a></td>
        <td>4</td>
        <td>9498.653</td>
        <td>599.750</td>
    </tr>
    <tr>
        <td>1055</td>
        <td><a href=players.php?pid=69734&edition=5>vanquish.1</a></td>
        <td>4</td>
        <td>9498.800</td>
        <td>602.500</td>
    </tr>
    <tr>
        <td>1056</td>
        <td><a href=players.php?pid=28&edition=5><span style='color:#ffdd00;'>ric</span><span
                    style='color:#aaff22;'>hard</span><span style='color:#ff4400;'>e_e</span></a></td>
        <td>4</td>
        <td>9498.973</td>
        <td>605.750</td>
    </tr>
    <tr>
        <td>1057</td>
        <td><a href=players.php?pid=324&edition=5><span style='color:#ff6600;'>B</span><span
                    style='color:#ff8833;'>o</span><span style='color:#ffaa66;'>w</span><span
                    style='color:#ffcc99;'>r</span><span style='color:#ffeecc;'>i</span><span
                    style='color:#ffffff;'>s</span></a></td>
        <td>4</td>
        <td>9499.000</td>
        <td>606.250</td>
    </tr>
    <tr>
        <td>1058</td>
        <td><a href=players.php?pid=36128&edition=5>MakeViljami</a></td>
        <td>4</td>
        <td>9499.027</td>
        <td>606.750</td>
    </tr>
    <tr>
        <td>1059</td>
        <td><a href=players.php?pid=57885&edition=5>uJackz</a></td>
        <td>4</td>
        <td>9499.320</td>
        <td>612.250</td>
    </tr>
    <tr>
        <td>1060</td>
        <td><a href=players.php?pid=68472&edition=5>Kalitaris</a></td>
        <td>4</td>
        <td>9499.373</td>
        <td>613.250</td>
    </tr>
    <tr>
        <td>1061</td>
        <td><a href=players.php?pid=7958&edition=5><span
                    style='color:#ffffff;letter-spacing: -0.1em;font-size:smaller'>Ң&Delta;&Tau;々</span><span
                    style='color:#333333;letter-spacing: -0.1em;font-size:smaller'>&raquo;&nbsp;</span><span
                    style='color:#ffffff;letter-spacing: -0.1em;font-size:smaller'>ה&omicron;&tau;7</span><span
                    style='color:#333333;font-style:italic;'>harry</span></a></td>
        <td>4</td>
        <td>9499.480</td>
        <td>615.250</td>
    </tr>
    <tr>
        <td>1062</td>
        <td><a href=players.php?pid=67753&edition=5>Flex0hh</a></td>
        <td>4</td>
        <td>9499.640</td>
        <td>618.250</td>
    </tr>
    <tr>
        <td>1063</td>
        <td><a href=players.php?pid=68140&edition=5>tomattowo</a></td>
        <td>4</td>
        <td>9499.880</td>
        <td>622.750</td>
    </tr>
    <tr>
        <td>1064</td>
        <td><a href=players.php?pid=28102&edition=5>MaggyAyG</a></td>
        <td>4</td>
        <td>9499.893</td>
        <td>623.000</td>
    </tr>
    <tr>
        <td>1065</td>
        <td><a href=players.php?pid=25651&edition=5>vitsulol</a></td>
        <td>4</td>
        <td>9500.067</td>
        <td>626.250</td>
    </tr>
    <tr>
        <td>1066</td>
        <td><a href=players.php?pid=67675&edition=5>GoKart_Mozart_</a></td>
        <td>4</td>
        <td>9500.293</td>
        <td>630.500</td>
    </tr>
    <tr>
        <td>1067</td>
        <td><a href=players.php?pid=57044&edition=5><span style='font-weight:bold;'>&nbsp;</span><span
                    style='color:#ff0000;font-weight:bold;'>M</span><span
                    style='color:#ff2211;font-weight:bold;'>u</span><span
                    style='color:#ff4411;font-weight:bold;'>r</span><span
                    style='color:#ff5522;font-weight:bold;'>m</span><span
                    style='color:#ff7722;font-weight:bold;'>u</span><span
                    style='color:#ff9933;font-weight:bold;'>r</span></a></td>
        <td>4</td>
        <td>9500.347</td>
        <td>631.500</td>
    </tr>
    <tr>
        <td>1068</td>
        <td><a href=players.php?pid=69772&edition=5>chicknwingz</a></td>
        <td>4</td>
        <td>9500.360</td>
        <td>631.750</td>
    </tr>
    <tr>
        <td>1069</td>
        <td><a href=players.php?pid=6935&edition=5>DiamondDudeJD</a></td>
        <td>4</td>
        <td>9500.547</td>
        <td>635.250</td>
    </tr>
    <tr>
        <td>1070</td>
        <td><a href=players.php?pid=5336&edition=5>DaZzLe...</a></td>
        <td>4</td>
        <td>9500.600</td>
        <td>636.250</td>
    </tr>
    <tr>
        <td>1071</td>
        <td><a href=players.php?pid=46193&edition=5>PF_Laki</a></td>
        <td>4</td>
        <td>9500.827</td>
        <td>640.500</td>
    </tr>
    <tr>
        <td>1072</td>
        <td><a href=players.php?pid=68627&edition=5>kjkibbles_</a></td>
        <td>4</td>
        <td>9500.867</td>
        <td>641.250</td>
    </tr>
    <tr>
        <td>1073</td>
        <td><a href=players.php?pid=66416&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>|&nbsp;Nayte</span></a></td>
        <td>4</td>
        <td>9501.053</td>
        <td>644.750</td>
    </tr>
    <tr>
        <td>1074</td>
        <td><a href=players.php?pid=29821&edition=5>ross247sol</a></td>
        <td>4</td>
        <td>9501.160</td>
        <td>646.750</td>
    </tr>
    <tr>
        <td>1075</td>
        <td><a href=players.php?pid=16837&edition=5>CodeinxSprite</a></td>
        <td>4</td>
        <td>9501.400</td>
        <td>651.250</td>
    </tr>
    <tr>
        <td>1076</td>
        <td><a href=players.php?pid=67775&edition=5>talja1998</a></td>
        <td>4</td>
        <td>9501.707</td>
        <td>657.000</td>
    </tr>
    <tr>
        <td>1077</td>
        <td><a href=players.php?pid=55919&edition=5>joe</a></td>
        <td>4</td>
        <td>9501.947</td>
        <td>661.500</td>
    </tr>
    <tr>
        <td>1078</td>
        <td><a href=players.php?pid=36131&edition=5><span style='color:#66ffff;'>R</span><span
                    style='color:#44ffff;'>o</span><span style='color:#22ffff;'>b</span><span
                    style='color:#00ffff;'>n</span><span style='color:#00ffff;'>i</span><span
                    style='color:#00ccbb;'>o</span><span style='color:#009966;'>n</span></a></td>
        <td>4</td>
        <td>9502.080</td>
        <td>664.000</td>
    </tr>
    <tr>
        <td>1079</td>
        <td><a href=players.php?pid=33549&edition=5>OGnut.</a></td>
        <td>4</td>
        <td>9502.813</td>
        <td>677.750</td>
    </tr>
    <tr>
        <td>1080</td>
        <td><a href=players.php?pid=7411&edition=5><span style='color:#6600cc;'>3</span><span
                    style='color:#7711dd;'>n</span><span style='color:#8822ee;'>ri</span><span
                    style='color:#9933ff;'>k</span></a></td>
        <td>4</td>
        <td>9502.880</td>
        <td>679.000</td>
    </tr>
    <tr>
        <td>1081</td>
        <td><a href=players.php?pid=50397&edition=5>NOVA347_</a></td>
        <td>4</td>
        <td>9503.493</td>
        <td>690.500</td>
    </tr>
    <tr>
        <td>1082</td>
        <td><a href=players.php?pid=48934&edition=5><span style='color:#00ffff;font-weight:bold;'>Jon</span></a></td>
        <td>4</td>
        <td>9503.600</td>
        <td>692.500</td>
    </tr>
    <tr>
        <td>1083</td>
        <td><a href=players.php?pid=66817&edition=5>liquiddd</a></td>
        <td>4</td>
        <td>9503.720</td>
        <td>694.750</td>
    </tr>
    <tr>
        <td>1084</td>
        <td><a href=players.php?pid=12124&edition=5><span style='color:#ffffff;'>hl</span><span
                    style='color:#ff00ff;'>y</span><span style='color:#ffff00;'>y</span><span
                    style='color:#00ffff;'>y</span><span style='color:#aaaaaa;'>zz</span><span
                    style='color:#ffffff;'>rr</span></a></td>
        <td>4</td>
        <td>9503.760</td>
        <td>695.500</td>
    </tr>
    <tr>
        <td>1085</td>
        <td><a href=players.php?pid=6193&edition=5><span style='color:#9900cc;'>&theta;</span><span
                    style='color:#660088;'>ん</span><span style='color:#330044;'>ѣ</span><span
                    style='color:#000000;'>ェ</span><span style='color:#000000;'>ϐ</span><span
                    style='color:#330088;'>ő</span><span style='color:#6600ff;'>ע</span></a></td>
        <td>4</td>
        <td>9504.253</td>
        <td>704.750</td>
    </tr>
    <tr>
        <td>1086</td>
        <td><a href=players.php?pid=39870&edition=5>Isaactayy</a></td>
        <td>4</td>
        <td>9504.253</td>
        <td>704.750</td>
    </tr>
    <tr>
        <td>1087</td>
        <td><a href=players.php?pid=50267&edition=5><span style='color:#ff0000;'>ҟ</span><span
                    style='color:#aa0000;'>ヨ</span><span style='color:#550000;'>ŧ</span><span
                    style='color:#000000;'>&cent;</span><span style='color:#000000;'>Ħ</span><span
                    style='color:#111144;'>น</span><span style='color:#111177;'>や</span></a></td>
        <td>4</td>
        <td>9504.640</td>
        <td>712.000</td>
    </tr>
    <tr>
        <td>1088</td>
        <td><a href=players.php?pid=60471&edition=5>FIFTYNICO</a></td>
        <td>4</td>
        <td>9504.947</td>
        <td>717.750</td>
    </tr>
    <tr>
        <td>1089</td>
        <td><a href=players.php?pid=37067&edition=5><span style='color:#00ff00;'>L</span><span
                    style='color:#00ff44;'>c</span><span style='color:#00ff88;'>s</span><span
                    style='color:#00ffcc;'>.</span></a></td>
        <td>4</td>
        <td>9504.987</td>
        <td>718.500</td>
    </tr>
    <tr>
        <td>1090</td>
        <td><a href=players.php?pid=65521&edition=5><span style='color:#6633ff;'>D</span><span
                    style='color:#7722ff;'>em</span><span style='color:#8811ff;'>o</span></a></td>
        <td>4</td>
        <td>9505.760</td>
        <td>733.000</td>
    </tr>
    <tr>
        <td>1091</td>
        <td><a href=players.php?pid=67277&edition=5>Osterius_</a></td>
        <td>4</td>
        <td>9505.840</td>
        <td>734.500</td>
    </tr>
    <tr>
        <td>1092</td>
        <td><a href=players.php?pid=26107&edition=5>Jab_08</a></td>
        <td>4</td>
        <td>9505.987</td>
        <td>737.250</td>
    </tr>
    <tr>
        <td>1093</td>
        <td><a href=players.php?pid=32359&edition=5>n0s_TM</a></td>
        <td>4</td>
        <td>9506.080</td>
        <td>739.000</td>
    </tr>
    <tr>
        <td>1094</td>
        <td><a href=players.php?pid=30354&edition=5>Rypsey</a></td>
        <td>4</td>
        <td>9506.080</td>
        <td>739.000</td>
    </tr>
    <tr>
        <td>1095</td>
        <td><a href=players.php?pid=17173&edition=5>mayer...</a></td>
        <td>4</td>
        <td>9506.307</td>
        <td>743.250</td>
    </tr>
    <tr>
        <td>1096</td>
        <td><a href=players.php?pid=6462&edition=5>MustardF1</a></td>
        <td>4</td>
        <td>9506.533</td>
        <td>747.500</td>
    </tr>
    <tr>
        <td>1097</td>
        <td><a href=players.php?pid=10072&edition=5>Nitron</a></td>
        <td>4</td>
        <td>9506.960</td>
        <td>755.500</td>
    </tr>
    <tr>
        <td>1098</td>
        <td><a href=players.php?pid=52694&edition=5>PoggingtonBear</a></td>
        <td>4</td>
        <td>9507.027</td>
        <td>756.750</td>
    </tr>
    <tr>
        <td>1099</td>
        <td><a href=players.php?pid=51909&edition=5>MVDXJSON</a></td>
        <td>4</td>
        <td>9507.067</td>
        <td>757.500</td>
    </tr>
    <tr>
        <td>1100</td>
        <td><a href=players.php?pid=67065&edition=5>rfresh1</a></td>
        <td>4</td>
        <td>9507.080</td>
        <td>757.750</td>
    </tr>
    <tr>
        <td>1101</td>
        <td><a href=players.php?pid=67415&edition=5>Vil._</a></td>
        <td>4</td>
        <td>9507.547</td>
        <td>766.500</td>
    </tr>
    <tr>
        <td>1102</td>
        <td><a href=players.php?pid=48425&edition=5><span style='color:#000000;'>D</span><span
                    style='color:#ff0000;'>r</span><span style='color:#ffffff;'>Shnizzle</span></a></td>
        <td>4</td>
        <td>9508.173</td>
        <td>778.250</td>
    </tr>
    <tr>
        <td>1103</td>
        <td><a href=players.php?pid=71279&edition=5>V3RD1CTT</a></td>
        <td>4</td>
        <td>9508.653</td>
        <td>787.250</td>
    </tr>
    <tr>
        <td>1104</td>
        <td><a href=players.php?pid=65812&edition=5><span style='color:#ff6600;'>&lt;&deg;)</span><span
                    style='color:#ffcc00;'>&nbsp;E</span><span style='color:#ffbb00;'>s</span><span
                    style='color:#ff9900;'>u</span><span style='color:#ff8800;'>X</span><span
                    style='color:#ff6600;'>R</span></a></td>
        <td>4</td>
        <td>9508.733</td>
        <td>788.750</td>
    </tr>
    <tr>
        <td>1105</td>
        <td><a href=players.php?pid=11010&edition=5><span style='color:#ffccff;'>~</span><span
                    style='color:#ffddff;'>L</span><span style='color:#ffeeff;'>a</span><span
                    style='color:#ffffff;'>u</span><span style='color:#ffffff;'>r</span><span
                    style='color:#eeffff;'>a</span><span style='color:#ccffff;'>~</span></a></td>
        <td>4</td>
        <td>9509.053</td>
        <td>794.750</td>
    </tr>
    <tr>
        <td>1106</td>
        <td><a href=players.php?pid=48809&edition=5>Raquel_IG</a></td>
        <td>4</td>
        <td>9509.093</td>
        <td>795.500</td>
    </tr>
    <tr>
        <td>1107</td>
        <td><a href=players.php?pid=66163&edition=5><span style='color:#ff0000;'>R</span><span
                    style='color:#dd0000;'>e</span><span style='color:#bb0000;'>d</span><span
                    style='color:#990000;'>G</span><span style='color:#660000;'>h</span><span
                    style='color:#440000;'>o</span><span style='color:#220000;'>s</span><span
                    style='color:#000000;'>t</span></a></td>
        <td>4</td>
        <td>9509.160</td>
        <td>796.750</td>
    </tr>
    <tr>
        <td>1108</td>
        <td><a href=players.php?pid=70809&edition=5>horner00</a></td>
        <td>4</td>
        <td>9509.200</td>
        <td>797.500</td>
    </tr>
    <tr>
        <td>1109</td>
        <td><a href=players.php?pid=66453&edition=5>lundinho.</a></td>
        <td>4</td>
        <td>9509.347</td>
        <td>800.250</td>
    </tr>
    <tr>
        <td>1110</td>
        <td><a href=players.php?pid=8437&edition=5>d1ddes</a></td>
        <td>4</td>
        <td>9509.720</td>
        <td>807.250</td>
    </tr>
    <tr>
        <td>1111</td>
        <td><a href=players.php?pid=11710&edition=5><span style='color:#cc9900;'>k</span><span
                    style='color:#997700;'>i</span><span style='color:#665500;'>e</span><span
                    style='color:#332200;'>r</span><span style='color:#000000;'>u</span></a></td>
        <td>4</td>
        <td>9510.067</td>
        <td>813.750</td>
    </tr>
    <tr>
        <td>1112</td>
        <td><a href=players.php?pid=32684&edition=5>YOURiiTM</a></td>
        <td>4</td>
        <td>9510.080</td>
        <td>814.000</td>
    </tr>
    <tr>
        <td>1113</td>
        <td><a href=players.php?pid=51927&edition=5>IShaaaKa</a></td>
        <td>4</td>
        <td>9510.227</td>
        <td>816.750</td>
    </tr>
    <tr>
        <td>1114</td>
        <td><a href=players.php?pid=41188&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Leli_</span></a></td>
        <td>4</td>
        <td>9510.267</td>
        <td>817.500</td>
    </tr>
    <tr>
        <td>1115</td>
        <td><a href=players.php?pid=56314&edition=5>CharizardFire5</a></td>
        <td>4</td>
        <td>9510.307</td>
        <td>818.250</td>
    </tr>
    <tr>
        <td>1116</td>
        <td><a href=players.php?pid=66979&edition=5><span style='color:#6666ff;'>minuie</span></a></td>
        <td>4</td>
        <td>9510.867</td>
        <td>828.750</td>
    </tr>
    <tr>
        <td>1117</td>
        <td><a href=players.php?pid=12253&edition=5>Fayde</a></td>
        <td>4</td>
        <td>9511.387</td>
        <td>838.500</td>
    </tr>
    <tr>
        <td>1118</td>
        <td><a href=players.php?pid=62824&edition=5>AjnaTM</a></td>
        <td>4</td>
        <td>9511.520</td>
        <td>841.000</td>
    </tr>
    <tr>
        <td>1119</td>
        <td><a href=players.php?pid=10411&edition=5>stargamertom</a></td>
        <td>4</td>
        <td>9511.547</td>
        <td>841.500</td>
    </tr>
    <tr>
        <td>1120</td>
        <td><a href=players.php?pid=32183&edition=5><span style='color:#ff00ff;'>V</span><span
                    style='color:#cc00ff;'>i</span><span style='color:#9900ff;'>o</span><span
                    style='color:#9900ff;'>l</span><span style='color:#bb33ff;'>e</span><span
                    style='color:#cc66ff;'>t</span></a></td>
        <td>4</td>
        <td>9511.627</td>
        <td>843.000</td>
    </tr>
    <tr>
        <td>1121</td>
        <td><a href=players.php?pid=13299&edition=5>Audriel</a></td>
        <td>4</td>
        <td>9511.627</td>
        <td>843.000</td>
    </tr>
    <tr>
        <td>1122</td>
        <td><a href=players.php?pid=41538&edition=5>ChefPercent</a></td>
        <td>4</td>
        <td>9513.107</td>
        <td>870.750</td>
    </tr>
    <tr>
        <td>1123</td>
        <td><a href=players.php?pid=66279&edition=5>Y_Rewik</a></td>
        <td>4</td>
        <td>9513.133</td>
        <td>871.250</td>
    </tr>
    <tr>
        <td>1124</td>
        <td><a href=players.php?pid=38713&edition=5>Zartan97</a></td>
        <td>4</td>
        <td>9513.560</td>
        <td>879.250</td>
    </tr>
    <tr>
        <td>1125</td>
        <td><a href=players.php?pid=30925&edition=5>clen.TM</a></td>
        <td>4</td>
        <td>9513.680</td>
        <td>881.500</td>
    </tr>
    <tr>
        <td>1126</td>
        <td><a href=players.php?pid=44479&edition=5>Nolanhead_</a></td>
        <td>4</td>
        <td>9513.693</td>
        <td>881.750</td>
    </tr>
    <tr>
        <td>1127</td>
        <td><a href=players.php?pid=56765&edition=5>Cullan75</a></td>
        <td>4</td>
        <td>9513.787</td>
        <td>883.500</td>
    </tr>
    <tr>
        <td>1128</td>
        <td><a href=players.php?pid=66256&edition=5>Havoctm</a></td>
        <td>4</td>
        <td>9513.960</td>
        <td>886.750</td>
    </tr>
    <tr>
        <td>1129</td>
        <td><a href=players.php?pid=28068&edition=5><span style='color:#aaddee;'>w</span><span
                    style='color:#0000ff;'>ee</span><span style='color:#aaddee;'>lp</span></a></td>
        <td>4</td>
        <td>9514.907</td>
        <td>904.500</td>
    </tr>
    <tr>
        <td>1130</td>
        <td><a href=players.php?pid=41001&edition=5>GauthZu86</a></td>
        <td>4</td>
        <td>9514.907</td>
        <td>904.500</td>
    </tr>
    <tr>
        <td>1131</td>
        <td><a href=players.php?pid=31163&edition=5>Windho</a></td>
        <td>4</td>
        <td>9515.120</td>
        <td>908.500</td>
    </tr>
    <tr>
        <td>1132</td>
        <td><a href=players.php?pid=50504&edition=5>AKKIZ2022</a></td>
        <td>4</td>
        <td>9515.680</td>
        <td>919.000</td>
    </tr>
    <tr>
        <td>1133</td>
        <td><a href=players.php?pid=64429&edition=5>goldenshot93</a></td>
        <td>4</td>
        <td>9516.080</td>
        <td>926.500</td>
    </tr>
    <tr>
        <td>1134</td>
        <td><a href=players.php?pid=30292&edition=5>:prayge:</a></td>
        <td>4</td>
        <td>9516.573</td>
        <td>935.750</td>
    </tr>
    <tr>
        <td>1135</td>
        <td><a href=players.php?pid=48196&edition=5>SRVSNSK.</a></td>
        <td>4</td>
        <td>9516.773</td>
        <td>939.500</td>
    </tr>
    <tr>
        <td>1136</td>
        <td><a href=players.php?pid=6549&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;</span><span style='color:#00ee00;'>Gr:e::e:p</span></a></td>
        <td>4</td>
        <td>9516.880</td>
        <td>941.500</td>
    </tr>
    <tr>
        <td>1137</td>
        <td><a href=players.php?pid=40489&edition=5><span style='color:#00ff33;'>J</span><span
                    style='color:#11ff55;'>4</span><span style='color:#11ff88;'>P</span><span
                    style='color:#22ffaa;'>S</span><span style='color:#22ffdd;'>3</span><span
                    style='color:#33ffff;'>R</span></a></td>
        <td>4</td>
        <td>9518.133</td>
        <td>965.000</td>
    </tr>
    <tr>
        <td>1138</td>
        <td><a href=players.php?pid=12910&edition=5>ShockerZNN</a></td>
        <td>4</td>
        <td>9518.373</td>
        <td>969.500</td>
    </tr>
    <tr>
        <td>1139</td>
        <td><a href=players.php?pid=51870&edition=5><span style='color:#339900;'>v</span><span
                    style='color:#55bb00;'>e</span><span style='color:#66cc00;'>g</span></a></td>
        <td>4</td>
        <td>9518.747</td>
        <td>976.500</td>
    </tr>
    <tr>
        <td>1140</td>
        <td><a href=players.php?pid=8169&edition=5>Colgate94</a></td>
        <td>4</td>
        <td>9519.533</td>
        <td>991.250</td>
    </tr>
    <tr>
        <td>1141</td>
        <td><a href=players.php?pid=66301&edition=5>KaiusB0nnus</a></td>
        <td>4</td>
        <td>9520.107</td>
        <td>1002.000</td>
    </tr>
    <tr>
        <td>1142</td>
        <td><a href=players.php?pid=67721&edition=5>henrikmk1</a></td>
        <td>4</td>
        <td>9520.173</td>
        <td>1003.250</td>
    </tr>
    <tr>
        <td>1143</td>
        <td><a href=players.php?pid=36100&edition=5>Adobz</a></td>
        <td>4</td>
        <td>9520.733</td>
        <td>1013.750</td>
    </tr>
    <tr>
        <td>1144</td>
        <td><a href=players.php?pid=25617&edition=5>hdnK</a></td>
        <td>4</td>
        <td>9522.013</td>
        <td>1037.750</td>
    </tr>
    <tr>
        <td>1145</td>
        <td><a href=players.php?pid=65301&edition=5>Catlegg_GE</a></td>
        <td>4</td>
        <td>9522.467</td>
        <td>1046.250</td>
    </tr>
    <tr>
        <td>1146</td>
        <td><a href=players.php?pid=42049&edition=5><span style='color:#66ff33;'>R</span><span
                    style='color:#99ff99;'>y</span><span style='color:#00ffff;'>C</span><span
                    style='color:#33ffff;'>r</span><span style='color:#66ffff;'>o</span><span
                    style='color:#99ffff;'>w</span></a></td>
        <td>3</td>
        <td>9602.747</td>
        <td>68.667</td>
    </tr>
    <tr>
        <td>1147</td>
        <td><a href=players.php?pid=57856&edition=5>jeyerr</a></td>
        <td>3</td>
        <td>9604.413</td>
        <td>110.333</td>
    </tr>
    <tr>
        <td>1148</td>
        <td><a href=players.php?pid=66891&edition=5>Silverskilla</a></td>
        <td>3</td>
        <td>9604.547</td>
        <td>113.667</td>
    </tr>
    <tr>
        <td>1149</td>
        <td><a href=players.php?pid=63547&edition=5>Ricardisthebest</a></td>
        <td>3</td>
        <td>9605.773</td>
        <td>144.333</td>
    </tr>
    <tr>
        <td>1150</td>
        <td><a href=players.php?pid=68036&edition=5>Maxoucsb</a></td>
        <td>3</td>
        <td>9606.400</td>
        <td>160.000</td>
    </tr>
    <tr>
        <td>1151</td>
        <td><a href=players.php?pid=34&edition=5>Spongelikezz</a></td>
        <td>3</td>
        <td>9606.427</td>
        <td>160.667</td>
    </tr>
    <tr>
        <td>1152</td>
        <td><a href=players.php?pid=39120&edition=5>ClaymoreClexTTV</a></td>
        <td>3</td>
        <td>9607.787</td>
        <td>194.667</td>
    </tr>
    <tr>
        <td>1153</td>
        <td><a href=players.php?pid=2233&edition=5><span style='color:#ffcccc;'>&raquo;</span><span
                    style='color:#ffffff;'>Ј&upsilon;ѕт&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>ฟ&sigma;ѕ</span><span
                    style='color:#ffcccc;font-style:italic;'>เै</span><span
                    style='color:#ffffff;font-style:italic;'>Ŀє.</span></a></td>
        <td>3</td>
        <td>9607.893</td>
        <td>197.333</td>
    </tr>
    <tr>
        <td>1154</td>
        <td><a href=players.php?pid=53969&edition=5>xArcticBerry</a></td>
        <td>3</td>
        <td>9607.973</td>
        <td>199.333</td>
    </tr>
    <tr>
        <td>1155</td>
        <td><a href=players.php?pid=11372&edition=5>ed&nbsp;<span style='color:#aa8855;'>:ben:</span></a></td>
        <td>3</td>
        <td>9608.227</td>
        <td>205.667</td>
    </tr>
    <tr>
        <td>1156</td>
        <td><a href=players.php?pid=23610&edition=5>Cheetek</a></td>
        <td>3</td>
        <td>9608.547</td>
        <td>213.667</td>
    </tr>
    <tr>
        <td>1157</td>
        <td><a href=players.php?pid=67852&edition=5><span style='color:#7711dd;'>U</span><span
                    style='color:#221122;'>T</span><span style='color:#221122;'>Z</span><span
                    style='color:#7711dd;'>5</span></a></td>
        <td>3</td>
        <td>9608.773</td>
        <td>219.333</td>
    </tr>
    <tr>
        <td>1158</td>
        <td><a href=players.php?pid=56819&edition=5>k<span style='color:#000000;'>b</span></a></td>
        <td>3</td>
        <td>9609.160</td>
        <td>229.000</td>
    </tr>
    <tr>
        <td>1159</td>
        <td><a href=players.php?pid=45136&edition=5><span style='color:#118877;'>H</span><span
                    style='color:#119977;'>a</span><span style='color:#119977;'>c</span><span
                    style='color:#11aa77;'>h</span><span style='color:#11aa77;'>i</span><span
                    style='color:#11bb77;'>i</span><span style='color:#11cc77;'>T</span><span
                    style='color:#22cc77;'>M</span></a></td>
        <td>3</td>
        <td>9609.667</td>
        <td>241.667</td>
    </tr>
    <tr>
        <td>1160</td>
        <td><a href=players.php?pid=65900&edition=5>rently_</a></td>
        <td>3</td>
        <td>9609.853</td>
        <td>246.333</td>
    </tr>
    <tr>
        <td>1161</td>
        <td><a href=players.php?pid=44&edition=5><span style='color:#ffffff;'>PringleGuy.</span><span
                    style='color:#ccccff;'>K</span><span style='color:#ccccff;'>a</span><span
                    style='color:#bbbbff;'>c</span><span style='color:#bb99ff;'>c</span><span
                    style='color:#aa88ff;'>h</span><span style='color:#9966ff;'>i</span></a></td>
        <td>3</td>
        <td>9610.040</td>
        <td>251.000</td>
    </tr>
    <tr>
        <td>1162</td>
        <td><a href=players.php?pid=2367&edition=5><span style='color:#ff0000;font-weight:bold;'>G</span><span
                    style='color:#ff3333;font-weight:bold;'>e</span><span
                    style='color:#ff6666;font-weight:bold;'>l</span><span
                    style='color:#ff9999;font-weight:bold;'>u</span><span
                    style='color:#ffcccc;font-weight:bold;'>i</span><span
                    style='color:#ffffff;font-weight:bold;'>d</span><span
                    style='color:#ffffff;font-weight:bold;'>义</span><span
                    style='color:#bbbbee;font-weight:bold;'>e</span><span
                    style='color:#8888ee;font-weight:bold;'>r</span><span
                    style='color:#4444dd;font-weight:bold;'>T</span><span
                    style='color:#0000cc;font-weight:bold;'>M</span></a></td>
        <td>3</td>
        <td>9610.187</td>
        <td>254.667</td>
    </tr>
    <tr>
        <td>1163</td>
        <td><a href=players.php?pid=7528&edition=5>CommeToi</a></td>
        <td>3</td>
        <td>9610.227</td>
        <td>255.667</td>
    </tr>
    <tr>
        <td>1164</td>
        <td><a href=players.php?pid=66172&edition=5><span style='color:#cc00ff;'>T</span><span
                    style='color:#aa33ff;'>i</span><span style='color:#8855ff;'>l</span><span
                    style='color:#6688ff;'>t</span><span style='color:#44aaff;'>.</span><span
                    style='color:#22ddff;'>T</span><span style='color:#00ffff;'>M</span></a></td>
        <td>3</td>
        <td>9610.347</td>
        <td>258.667</td>
    </tr>
    <tr>
        <td>1165</td>
        <td><a href=players.php?pid=9614&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;El_Scorpio</span></a></td>
        <td>3</td>
        <td>9610.387</td>
        <td>259.667</td>
    </tr>
    <tr>
        <td>1166</td>
        <td><a href=players.php?pid=69127&edition=5>mc_V1nKe</a></td>
        <td>3</td>
        <td>9611.387</td>
        <td>284.667</td>
    </tr>
    <tr>
        <td>1167</td>
        <td><a href=players.php?pid=69292&edition=5>V_LEX</a></td>
        <td>3</td>
        <td>9611.867</td>
        <td>296.667</td>
    </tr>
    <tr>
        <td>1168</td>
        <td><a href=players.php?pid=46122&edition=5>MinelixTM</a></td>
        <td>3</td>
        <td>9612.107</td>
        <td>302.667</td>
    </tr>
    <tr>
        <td>1169</td>
        <td><a href=players.php?pid=69583&edition=5>ThrusterTool</a></td>
        <td>3</td>
        <td>9612.173</td>
        <td>304.333</td>
    </tr>
    <tr>
        <td>1170</td>
        <td><a href=players.php?pid=26578&edition=5>Andreas01TM</a></td>
        <td>3</td>
        <td>9612.187</td>
        <td>304.667</td>
    </tr>
    <tr>
        <td>1171</td>
        <td><a href=players.php?pid=66325&edition=5><span style='color:#bb11dd;font-weight:bold;'>y</span><span
                    style='color:#bb11cc;font-weight:bold;'>&nbsp;</span><span
                    style='color:#aa11cc;font-weight:bold;'>u</span><span
                    style='color:#9911bb;font-weight:bold;'>&nbsp;</span><span
                    style='color:#9911bb;font-weight:bold;'>i</span><span
                    style='color:#8811aa;font-weight:bold;'>&nbsp;</span><span
                    style='color:#7711aa;font-weight:bold;'>n</span><span
                    style='color:#771199;font-weight:bold;'>&nbsp;</span><span
                    style='color:#661199;font-weight:bold;'>e</span></a></td>
        <td>3</td>
        <td>9612.293</td>
        <td>307.333</td>
    </tr>
    <tr>
        <td>1172</td>
        <td><a href=players.php?pid=6779&edition=5>Jakkoy</a></td>
        <td>3</td>
        <td>9612.440</td>
        <td>311.000</td>
    </tr>
    <tr>
        <td>1173</td>
        <td><a href=players.php?pid=69599&edition=5>PR0LL0X</a></td>
        <td>3</td>
        <td>9612.440</td>
        <td>311.000</td>
    </tr>
    <tr>
        <td>1174</td>
        <td><a href=players.php?pid=944&edition=5>Terminator.TM</a></td>
        <td>3</td>
        <td>9612.733</td>
        <td>318.333</td>
    </tr>
    <tr>
        <td>1175</td>
        <td><a href=players.php?pid=7819&edition=5>Schlonzbob</a></td>
        <td>3</td>
        <td>9612.747</td>
        <td>318.667</td>
    </tr>
    <tr>
        <td>1176</td>
        <td><a href=players.php?pid=87&edition=5><span style='color:#ffffff;'>н</span><span
                    style='color:#0000ff;'>&epsilon;</span><span style='color:#ffffff;'>&kappa;&upsilon;</span></a></td>
        <td>3</td>
        <td>9612.933</td>
        <td>323.333</td>
    </tr>
    <tr>
        <td>1177</td>
        <td><a href=players.php?pid=54384&edition=5>Akiro_TM</a></td>
        <td>3</td>
        <td>9613.040</td>
        <td>326.000</td>
    </tr>
    <tr>
        <td>1178</td>
        <td><a href=players.php?pid=18935&edition=5>TEH_CRAW</a></td>
        <td>3</td>
        <td>9613.320</td>
        <td>333.000</td>
    </tr>
    <tr>
        <td>1179</td>
        <td><a href=players.php?pid=34727&edition=5>DuckOnQuackUwU</a></td>
        <td>3</td>
        <td>9613.547</td>
        <td>338.667</td>
    </tr>
    <tr>
        <td>1180</td>
        <td><a href=players.php?pid=65334&edition=5>veturikuski_</a></td>
        <td>3</td>
        <td>9613.707</td>
        <td>342.667</td>
    </tr>
    <tr>
        <td>1181</td>
        <td><a href=players.php?pid=48281&edition=5>tyando10</a></td>
        <td>3</td>
        <td>9614.027</td>
        <td>350.667</td>
    </tr>
    <tr>
        <td>1182</td>
        <td><a href=players.php?pid=62894&edition=5>wantrua</a></td>
        <td>3</td>
        <td>9614.067</td>
        <td>351.667</td>
    </tr>
    <tr>
        <td>1183</td>
        <td><a href=players.php?pid=24046&edition=5><span style='color:#33ffff;'>A</span><span
                    style='color:#55ddff;'>u</span><span style='color:#66bbee;'>t</span><span
                    style='color:#8899ee;'>o</span><span style='color:#aa66dd;'>C</span><span
                    style='color:#cc44dd;'>a</span><span style='color:#dd22cc;'>t</span><span
                    style='color:#ff00cc;'>s</span></a></td>
        <td>3</td>
        <td>9614.507</td>
        <td>362.667</td>
    </tr>
    <tr>
        <td>1184</td>
        <td><a href=players.php?pid=4264&edition=5>Massa.4PF</a></td>
        <td>3</td>
        <td>9614.560</td>
        <td>364.000</td>
    </tr>
    <tr>
        <td>1185</td>
        <td><a href=players.php?pid=33993&edition=5>FauxPlays</a></td>
        <td>3</td>
        <td>9614.627</td>
        <td>365.667</td>
    </tr>
    <tr>
        <td>1186</td>
        <td><a href=players.php?pid=38155&edition=5>SusNopTM</a></td>
        <td>3</td>
        <td>9614.880</td>
        <td>372.000</td>
    </tr>
    <tr>
        <td>1187</td>
        <td><a href=players.php?pid=47150&edition=5>Scope450</a></td>
        <td>3</td>
        <td>9614.893</td>
        <td>372.333</td>
    </tr>
    <tr>
        <td>1188</td>
        <td><a href=players.php?pid=4109&edition=5>silas992</a></td>
        <td>3</td>
        <td>9614.920</td>
        <td>373.000</td>
    </tr>
    <tr>
        <td>1189</td>
        <td><a href=players.php?pid=63656&edition=5>rogurgo</a></td>
        <td>3</td>
        <td>9614.933</td>
        <td>373.333</td>
    </tr>
    <tr>
        <td>1190</td>
        <td><a href=players.php?pid=10546&edition=5>Tobizzy_TM</a></td>
        <td>3</td>
        <td>9615.653</td>
        <td>391.333</td>
    </tr>
    <tr>
        <td>1191</td>
        <td><a href=players.php?pid=23962&edition=5>Crossy2882</a></td>
        <td>3</td>
        <td>9615.720</td>
        <td>393.000</td>
    </tr>
    <tr>
        <td>1192</td>
        <td><a href=players.php?pid=67254&edition=5>SkullCake12</a></td>
        <td>3</td>
        <td>9615.840</td>
        <td>396.000</td>
    </tr>
    <tr>
        <td>1193</td>
        <td><a href=players.php?pid=8314&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Skinny</span></a></td>
        <td>3</td>
        <td>9615.907</td>
        <td>397.667</td>
    </tr>
    <tr>
        <td>1194</td>
        <td><a href=players.php?pid=53906&edition=5>Skeemz905</a></td>
        <td>3</td>
        <td>9615.920</td>
        <td>398.000</td>
    </tr>
    <tr>
        <td>1195</td>
        <td><a href=players.php?pid=39777&edition=5>OspreyTM</a></td>
        <td>3</td>
        <td>9616.000</td>
        <td>400.000</td>
    </tr>
    <tr>
        <td>1196</td>
        <td><a href=players.php?pid=51679&edition=5><span style='color:#000000;'>FrosS</span></a></td>
        <td>3</td>
        <td>9616.387</td>
        <td>409.667</td>
    </tr>
    <tr>
        <td>1197</td>
        <td><a href=players.php?pid=71244&edition=5>lolo___01</a></td>
        <td>3</td>
        <td>9616.587</td>
        <td>414.667</td>
    </tr>
    <tr>
        <td>1198</td>
        <td><a href=players.php?pid=66410&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;P1.teDeBiere</span></a></td>
        <td>3</td>
        <td>9616.600</td>
        <td>415.000</td>
    </tr>
    <tr>
        <td>1199</td>
        <td><a href=players.php?pid=5340&edition=5>FerxGG</a></td>
        <td>3</td>
        <td>9616.600</td>
        <td>415.000</td>
    </tr>
    <tr>
        <td>1200</td>
        <td><a href=players.php?pid=70376&edition=5>Uberpangolin</a></td>
        <td>3</td>
        <td>9616.680</td>
        <td>417.000</td>
    </tr>
    <tr>
        <td>1201</td>
        <td><a href=players.php?pid=38685&edition=5>Jalt96</a></td>
        <td>3</td>
        <td>9616.893</td>
        <td>422.333</td>
    </tr>
    <tr>
        <td>1202</td>
        <td><a href=players.php?pid=29285&edition=5><span style='color:#2200ff;font-weight:bold;'>L</span><span
                    style='color:#3300ff;font-weight:bold;'>e</span><span
                    style='color:#5500ff;font-weight:bold;'>o</span><span
                    style='color:#8800ff;font-weight:bold;'>p</span><span
                    style='color:#9900ff;font-weight:bold;'>o</span><span
                    style='color:#aa00ff;font-weight:bold;'>l</span><span
                    style='color:#bb00ff;font-weight:bold;'>d</span></a></td>
        <td>3</td>
        <td>9617.013</td>
        <td>425.333</td>
    </tr>
    <tr>
        <td>1203</td>
        <td><a href=players.php?pid=4333&edition=5>:pepepoint:</a></td>
        <td>3</td>
        <td>9617.160</td>
        <td>429.000</td>
    </tr>
    <tr>
        <td>1204</td>
        <td><a href=players.php?pid=70999&edition=5>TTV_Skeegan123</a></td>
        <td>3</td>
        <td>9617.280</td>
        <td>432.000</td>
    </tr>
    <tr>
        <td>1205</td>
        <td><a href=players.php?pid=68367&edition=5>BigMattandFries</a></td>
        <td>3</td>
        <td>9617.400</td>
        <td>435.000</td>
    </tr>
    <tr>
        <td>1206</td>
        <td><a href=players.php?pid=53584&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;LaFleche_&nbsp;</span></a></td>
        <td>3</td>
        <td>9617.840</td>
        <td>446.000</td>
    </tr>
    <tr>
        <td>1207</td>
        <td><a href=players.php?pid=47062&edition=5>OZY.TM</a></td>
        <td>3</td>
        <td>9617.920</td>
        <td>448.000</td>
    </tr>
    <tr>
        <td>1208</td>
        <td><a href=players.php?pid=26207&edition=5>GyattRadar</a></td>
        <td>3</td>
        <td>9618.080</td>
        <td>452.000</td>
    </tr>
    <tr>
        <td>1209</td>
        <td><a href=players.php?pid=57349&edition=5>NurNils_TM</a></td>
        <td>3</td>
        <td>9618.133</td>
        <td>453.333</td>
    </tr>
    <tr>
        <td>1210</td>
        <td><a href=players.php?pid=61200&edition=5>GxRustyxG</a></td>
        <td>3</td>
        <td>9618.187</td>
        <td>454.667</td>
    </tr>
    <tr>
        <td>1211</td>
        <td><a href=players.php?pid=40348&edition=5>Amnesia1-TM</a></td>
        <td>3</td>
        <td>9618.467</td>
        <td>461.667</td>
    </tr>
    <tr>
        <td>1212</td>
        <td><a href=players.php?pid=70626&edition=5>AExXontros</a></td>
        <td>3</td>
        <td>9618.480</td>
        <td>462.000</td>
    </tr>
    <tr>
        <td>1213</td>
        <td><a href=players.php?pid=20893&edition=5>CcrazZynGamer</a></td>
        <td>3</td>
        <td>9618.507</td>
        <td>462.667</td>
    </tr>
    <tr>
        <td>1214</td>
        <td><a href=players.php?pid=1944&edition=5>daweTM</a></td>
        <td>3</td>
        <td>9618.520</td>
        <td>463.000</td>
    </tr>
    <tr>
        <td>1215</td>
        <td><a href=players.php?pid=10397&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>alex-WRR</span></a>
        </td>
        <td>3</td>
        <td>9618.640</td>
        <td>466.000</td>
    </tr>
    <tr>
        <td>1216</td>
        <td><a href=players.php?pid=66137&edition=5>Numb3r_</a></td>
        <td>3</td>
        <td>9618.653</td>
        <td>466.333</td>
    </tr>
    <tr>
        <td>1217</td>
        <td><a href=players.php?pid=43106&edition=5><span style='color:#00dd00;'>Jet</span></a></td>
        <td>3</td>
        <td>9618.707</td>
        <td>467.667</td>
    </tr>
    <tr>
        <td>1218</td>
        <td><a href=players.php?pid=8774&edition=5><span style='color:#ff0000;'>S</span><span
                    style='color:#ff3333;'>a</span><span style='color:#ff6666;'>n</span><span
                    style='color:#ff9999;'>c</span><span style='color:#ffcccc;'>h</span><span
                    style='color:#ffffff;'>o</span></a></td>
        <td>3</td>
        <td>9619.240</td>
        <td>481.000</td>
    </tr>
    <tr>
        <td>1219</td>
        <td><a href=players.php?pid=69103&edition=5>Peltrux</a></td>
        <td>3</td>
        <td>9619.373</td>
        <td>484.333</td>
    </tr>
    <tr>
        <td>1220</td>
        <td><a href=players.php?pid=42942&edition=5><span style='color:#ff0000;'>C</span><span
                    style='color:#cccccc;'>w_fabi</span></a></td>
        <td>3</td>
        <td>9619.627</td>
        <td>490.667</td>
    </tr>
    <tr>
        <td>1221</td>
        <td><a href=players.php?pid=67068&edition=5><span style='color:#ff0000;'>A</span><span
                    style='color:#ee0022;'>l</span><span style='color:#ee1133;'>f</span><span
                    style='color:#dd1155;'>i</span><span style='color:#cc1177;'>e</span><span
                    style='color:#cc2288;'>_</span><span style='color:#bb22aa;'>2</span><span
                    style='color:#aa22cc;'>7</span>0<span style='color:#9933ff;'>6</span></a></td>
        <td>3</td>
        <td>9619.667</td>
        <td>491.667</td>
    </tr>
    <tr>
        <td>1222</td>
        <td><a href=players.php?pid=45734&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;|&nbsp;</span><span
                    style='color:#ff0000;font-style:italic;font-weight:bold;'>&nbsp;Esteban24</span></a></td>
        <td>3</td>
        <td>9619.707</td>
        <td>492.667</td>
    </tr>
    <tr>
        <td>1223</td>
        <td><a href=players.php?pid=58562&edition=5><span style='color:#00ffff;'>S</span><span
                    style='color:#11eeff;'>T</span><span style='color:#22ddff;'>U</span><span
                    style='color:#33ddff;'>N</span><span style='color:#33ccff;'>T</span><span
                    style='color:#44bbff;'>&nbsp;</span><span style='color:#55aaff;'>|</span><span
                    style='color:#66aaff;'>&nbsp;</span><span style='color:#7799ff;'>ϻ</span><span
                    style='color:#8888ff;'>&alpha;</span><span style='color:#9977ff;'>&kappa;</span><span
                    style='color:#9966ff;'>&kappa;</span><span style='color:#aa66ff;'>Ѓ</span><span
                    style='color:#bb55ff;'>έ</span><span style='color:#cc44ff;'>Ϩ:clueless:</span></a></td>
        <td>3</td>
        <td>9619.707</td>
        <td>492.667</td>
    </tr>
    <tr>
        <td>1224</td>
        <td><a href=players.php?pid=24124&edition=5>Javacosa</a></td>
        <td>3</td>
        <td>9619.720</td>
        <td>493.000</td>
    </tr>
    <tr>
        <td>1225</td>
        <td><a href=players.php?pid=46767&edition=5>Brezzly</a></td>
        <td>3</td>
        <td>9619.853</td>
        <td>496.333</td>
    </tr>
    <tr>
        <td>1226</td>
        <td><a href=players.php?pid=11679&edition=5><span style='color:#9900ff;'>R</span><span
                    style='color:#aa22ff;'>o</span><span style='color:#aa33ff;'>a</span><span
                    style='color:#bb55ff;'>d</span><span style='color:#cc77ff;'>s</span><span
                    style='color:#cc88ff;'>t</span><span style='color:#ddaaff;'>e</span><span
                    style='color:#eeccff;'>r</span><span style='color:#eeddff;'>T</span><span
                    style='color:#ffffff;'>M</span></a></td>
        <td>3</td>
        <td>9620.080</td>
        <td>502.000</td>
    </tr>
    <tr>
        <td>1227</td>
        <td><a href=players.php?pid=67125&edition=5>TuesdayAtFour</a></td>
        <td>3</td>
        <td>9620.253</td>
        <td>506.333</td>
    </tr>
    <tr>
        <td>1228</td>
        <td><a href=players.php?pid=66296&edition=5>Pilososs</a></td>
        <td>3</td>
        <td>9620.293</td>
        <td>507.333</td>
    </tr>
    <tr>
        <td>1229</td>
        <td><a href=players.php?pid=67459&edition=5>DropKickDrum</a></td>
        <td>3</td>
        <td>9620.760</td>
        <td>519.000</td>
    </tr>
    <tr>
        <td>1230</td>
        <td><a href=players.php?pid=65101&edition=5>loafbarks</a></td>
        <td>3</td>
        <td>9620.880</td>
        <td>522.000</td>
    </tr>
    <tr>
        <td>1231</td>
        <td><a href=players.php?pid=65695&edition=5>potatomato34</a></td>
        <td>3</td>
        <td>9620.920</td>
        <td>523.000</td>
    </tr>
    <tr>
        <td>1232</td>
        <td><a href=players.php?pid=34758&edition=5>my_name_deez</a></td>
        <td>3</td>
        <td>9621.053</td>
        <td>526.333</td>
    </tr>
    <tr>
        <td>1233</td>
        <td><a href=players.php?pid=11996&edition=5><span style='color:#0000ff;font-weight:bold;'>&nbsp;loliu</span></a>
        </td>
        <td>3</td>
        <td>9621.467</td>
        <td>536.667</td>
    </tr>
    <tr>
        <td>1234</td>
        <td><a href=players.php?pid=52393&edition=5>B0NES-TM</a></td>
        <td>3</td>
        <td>9621.627</td>
        <td>540.667</td>
    </tr>
    <tr>
        <td>1235</td>
        <td><a href=players.php?pid=32232&edition=5>WiverKing_</a></td>
        <td>3</td>
        <td>9621.640</td>
        <td>541.000</td>
    </tr>
    <tr>
        <td>1236</td>
        <td><a href=players.php?pid=66511&edition=5>Yortey</a></td>
        <td>3</td>
        <td>9621.787</td>
        <td>544.667</td>
    </tr>
    <tr>
        <td>1237</td>
        <td><a href=players.php?pid=9592&edition=5>Tede0000</a></td>
        <td>3</td>
        <td>9621.893</td>
        <td>547.333</td>
    </tr>
    <tr>
        <td>1238</td>
        <td><a href=players.php?pid=28341&edition=5>HChavez7</a></td>
        <td>3</td>
        <td>9621.987</td>
        <td>549.667</td>
    </tr>
    <tr>
        <td>1239</td>
        <td><a href=players.php?pid=36301&edition=5><span style='color:#009900;'>D</span><span
                    style='color:#22aa22;'>E</span><span style='color:#33bb33;'>G</span><span
                    style='color:#55bb55;'>S</span><span style='color:#66cc66;'>&nbsp;</span><span
                    style='color:#ffffff;'>iesauka</span></a></td>
        <td>3</td>
        <td>9622.120</td>
        <td>553.000</td>
    </tr>
    <tr>
        <td>1240</td>
        <td><a href=players.php?pid=66347&edition=5>Spoxes</a></td>
        <td>3</td>
        <td>9622.320</td>
        <td>558.000</td>
    </tr>
    <tr>
        <td>1241</td>
        <td><a href=players.php?pid=60802&edition=5>GusChiggins420</a></td>
        <td>3</td>
        <td>9622.400</td>
        <td>560.000</td>
    </tr>
    <tr>
        <td>1242</td>
        <td><a href=players.php?pid=66846&edition=5><span style='color:#aa33dd;'>D</span><span
                    style='color:#8855aa;'>э</span><span style='color:#667766;'>Ĥ</span><span
                    style='color:#44aa33;'>&phi;</span></a></td>
        <td>3</td>
        <td>9622.827</td>
        <td>570.667</td>
    </tr>
    <tr>
        <td>1243</td>
        <td><a href=players.php?pid=21843&edition=5>H̸̓͘a̸͆̂h̸̏́ā̵̀X̷̓̄D̵͌̋</a></td>
        <td>3</td>
        <td>9622.987</td>
        <td>574.667</td>
    </tr>
    <tr>
        <td>1244</td>
        <td><a href=players.php?pid=70550&edition=5>CorsaiR</a></td>
        <td>3</td>
        <td>9623.053</td>
        <td>576.333</td>
    </tr>
    <tr>
        <td>1245</td>
        <td><a href=players.php?pid=6332&edition=5><span
                    style='color:#ffffff;font-style:italic;'>&not;&nbsp;</span><span
                    style='color:#ff00ff;font-style:italic;'>&eta;Ь&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&raquo;&nbsp;:orangutan:</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;</span></a></td>
        <td>3</td>
        <td>9623.133</td>
        <td>578.333</td>
    </tr>
    <tr>
        <td>1246</td>
        <td><a href=players.php?pid=55131&edition=5>Affenlie</a></td>
        <td>3</td>
        <td>9623.227</td>
        <td>580.667</td>
    </tr>
    <tr>
        <td>1247</td>
        <td><a href=players.php?pid=69300&edition=5>Makkunouchii</a></td>
        <td>3</td>
        <td>9623.280</td>
        <td>582.000</td>
    </tr>
    <tr>
        <td>1248</td>
        <td><a href=players.php?pid=67223&edition=5>keeir</a></td>
        <td>3</td>
        <td>9623.307</td>
        <td>582.667</td>
    </tr>
    <tr>
        <td>1249</td>
        <td><a href=players.php?pid=29215&edition=5><span style='color:#0000cc;'>Ł</span><span
                    style='color:#0011dd;'>&sigma;</span><span style='color:#0022dd;'>&alpha;</span><span
                    style='color:#0033ee;'>ȡ</span><span style='color:#0044ee;'>ϊ</span><span
                    style='color:#0055ff;'>ก</span><span style='color:#0066ff;'>ǥ&nbsp;</span><span
                    style='color:#66ffff;'>々&nbsp;</span><span style='color:#ffffff;'>&not;&nbsp;</span><span
                    style='color:#ffcc00;'>Xicub</span></a></td>
        <td>3</td>
        <td>9623.520</td>
        <td>588.000</td>
    </tr>
    <tr>
        <td>1250</td>
        <td><a href=players.php?pid=65338&edition=5>MarkBee_</a></td>
        <td>3</td>
        <td>9623.560</td>
        <td>589.000</td>
    </tr>
    <tr>
        <td>1251</td>
        <td><a href=players.php?pid=70994&edition=5>ImGustaw</a></td>
        <td>3</td>
        <td>9623.600</td>
        <td>590.000</td>
    </tr>
    <tr>
        <td>1252</td>
        <td><a href=players.php?pid=70411&edition=5><span style='color:#ffffff;font-style:italic;'>krokzey</span></a>
        </td>
        <td>3</td>
        <td>9623.680</td>
        <td>592.000</td>
    </tr>
    <tr>
        <td>1253</td>
        <td><a href=players.php?pid=66014&edition=5>twenty007</a></td>
        <td>3</td>
        <td>9623.973</td>
        <td>599.333</td>
    </tr>
    <tr>
        <td>1254</td>
        <td><a href=players.php?pid=14359&edition=5>KFreeze1337</a></td>
        <td>3</td>
        <td>9623.973</td>
        <td>599.333</td>
    </tr>
    <tr>
        <td>1255</td>
        <td><a href=players.php?pid=46021&edition=5><span style='color:#00cc00;'>Le</span><span
                    style='color:#ff0000;'>Brouw</span></a></td>
        <td>3</td>
        <td>9624.173</td>
        <td>604.333</td>
    </tr>
    <tr>
        <td>1256</td>
        <td><a href=players.php?pid=1976&edition=5>YoYoDaa</a></td>
        <td>3</td>
        <td>9624.213</td>
        <td>605.333</td>
    </tr>
    <tr>
        <td>1257</td>
        <td><a href=players.php?pid=68505&edition=5>R1ezes</a></td>
        <td>3</td>
        <td>9624.280</td>
        <td>607.000</td>
    </tr>
    <tr>
        <td>1258</td>
        <td><a href=players.php?pid=69372&edition=5>Swift.za</a></td>
        <td>3</td>
        <td>9624.507</td>
        <td>612.667</td>
    </tr>
    <tr>
        <td>1259</td>
        <td><a href=players.php?pid=8062&edition=5>Cosmos24</a></td>
        <td>3</td>
        <td>9624.787</td>
        <td>619.667</td>
    </tr>
    <tr>
        <td>1260</td>
        <td><a href=players.php?pid=68946&edition=5>noseykart</a></td>
        <td>3</td>
        <td>9624.840</td>
        <td>621.000</td>
    </tr>
    <tr>
        <td>1261</td>
        <td><a href=players.php?pid=36710&edition=5>RendJis</a></td>
        <td>3</td>
        <td>9624.867</td>
        <td>621.667</td>
    </tr>
    <tr>
        <td>1262</td>
        <td><a href=players.php?pid=66565&edition=5>WetHorseLips</a></td>
        <td>3</td>
        <td>9624.960</td>
        <td>624.000</td>
    </tr>
    <tr>
        <td>1263</td>
        <td><a href=players.php?pid=10125&edition=5>Sombot</a></td>
        <td>3</td>
        <td>9625.053</td>
        <td>626.333</td>
    </tr>
    <tr>
        <td>1264</td>
        <td><a href=players.php?pid=37669&edition=5>Seys.TM</a></td>
        <td>3</td>
        <td>9625.147</td>
        <td>628.667</td>
    </tr>
    <tr>
        <td>1265</td>
        <td><a href=players.php?pid=58345&edition=5>myz95</a></td>
        <td>3</td>
        <td>9625.280</td>
        <td>632.000</td>
    </tr>
    <tr>
        <td>1266</td>
        <td><a href=players.php?pid=66654&edition=5>Russel_McDavid</a></td>
        <td>3</td>
        <td>9625.280</td>
        <td>632.000</td>
    </tr>
    <tr>
        <td>1267</td>
        <td><a href=players.php?pid=71356&edition=5>Arneau</a></td>
        <td>3</td>
        <td>9625.387</td>
        <td>634.667</td>
    </tr>
    <tr>
        <td>1268</td>
        <td><a href=players.php?pid=68468&edition=5>HaKenz.</a></td>
        <td>3</td>
        <td>9625.533</td>
        <td>638.333</td>
    </tr>
    <tr>
        <td>1269</td>
        <td><a href=players.php?pid=23492&edition=5>domijura</a></td>
        <td>3</td>
        <td>9625.693</td>
        <td>642.333</td>
    </tr>
    <tr>
        <td>1270</td>
        <td><a href=players.php?pid=71389&edition=5>Polgonite</a></td>
        <td>3</td>
        <td>9625.853</td>
        <td>646.333</td>
    </tr>
    <tr>
        <td>1271</td>
        <td><a href=players.php?pid=54930&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;</span><span style='color:#ff7700;'>Ok</span><span
                    style='color:#ffffff;'>Dacco</span></a></td>
        <td>3</td>
        <td>9626.027</td>
        <td>650.667</td>
    </tr>
    <tr>
        <td>1272</td>
        <td><a href=players.php?pid=65524&edition=5>Vilicus.</a></td>
        <td>3</td>
        <td>9626.107</td>
        <td>652.667</td>
    </tr>
    <tr>
        <td>1273</td>
        <td><a href=players.php?pid=66490&edition=5>ChampionMao</a></td>
        <td>3</td>
        <td>9626.107</td>
        <td>652.667</td>
    </tr>
    <tr>
        <td>1274</td>
        <td><a href=players.php?pid=7780&edition=5>agent30632</a></td>
        <td>3</td>
        <td>9626.600</td>
        <td>665.000</td>
    </tr>
    <tr>
        <td>1275</td>
        <td><a href=players.php?pid=8976&edition=5>Piglett-</a></td>
        <td>3</td>
        <td>9626.667</td>
        <td>666.667</td>
    </tr>
    <tr>
        <td>1276</td>
        <td><a href=players.php?pid=67542&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Noth</span></a></td>
        <td>3</td>
        <td>9626.680</td>
        <td>667.000</td>
    </tr>
    <tr>
        <td>1277</td>
        <td><a href=players.php?pid=38930&edition=5>Sedn494</a></td>
        <td>3</td>
        <td>9626.840</td>
        <td>671.000</td>
    </tr>
    <tr>
        <td>1278</td>
        <td><a href=players.php?pid=17281&edition=5>INGENTEA</a></td>
        <td>3</td>
        <td>9626.933</td>
        <td>673.333</td>
    </tr>
    <tr>
        <td>1279</td>
        <td><a href=players.php?pid=28898&edition=5>Denhomer</a></td>
        <td>3</td>
        <td>9626.987</td>
        <td>674.667</td>
    </tr>
    <tr>
        <td>1280</td>
        <td><a href=players.php?pid=56964&edition=5>LexUhhPro</a></td>
        <td>3</td>
        <td>9626.987</td>
        <td>674.667</td>
    </tr>
    <tr>
        <td>1281</td>
        <td><a href=players.php?pid=34296&edition=5>TyphlOwO</a></td>
        <td>3</td>
        <td>9627.040</td>
        <td>676.000</td>
    </tr>
    <tr>
        <td>1282</td>
        <td><a href=players.php?pid=68753&edition=5>SteveNonna</a></td>
        <td>3</td>
        <td>9627.080</td>
        <td>677.000</td>
    </tr>
    <tr>
        <td>1283</td>
        <td><a href=players.php?pid=53061&edition=5>Kevinn013</a></td>
        <td>3</td>
        <td>9627.080</td>
        <td>677.000</td>
    </tr>
    <tr>
        <td>1284</td>
        <td><a href=players.php?pid=39822&edition=5>ischhaltso</a></td>
        <td>3</td>
        <td>9627.093</td>
        <td>677.333</td>
    </tr>
    <tr>
        <td>1285</td>
        <td><a href=players.php?pid=68056&edition=5>Lukiou.</a></td>
        <td>3</td>
        <td>9627.320</td>
        <td>683.000</td>
    </tr>
    <tr>
        <td>1286</td>
        <td><a href=players.php?pid=23115&edition=5>kvampe</a></td>
        <td>3</td>
        <td>9627.347</td>
        <td>683.667</td>
    </tr>
    <tr>
        <td>1287</td>
        <td><a href=players.php?pid=53231&edition=5>R0mpeskjegg</a></td>
        <td>3</td>
        <td>9627.893</td>
        <td>697.333</td>
    </tr>
    <tr>
        <td>1288</td>
        <td><a href=players.php?pid=35031&edition=5>offline-.258</a></td>
        <td>3</td>
        <td>9628.160</td>
        <td>704.000</td>
    </tr>
    <tr>
        <td>1289</td>
        <td><a href=players.php?pid=70455&edition=5>Cyfrouille</a></td>
        <td>3</td>
        <td>9628.187</td>
        <td>704.667</td>
    </tr>
    <tr>
        <td>1290</td>
        <td><a href=players.php?pid=6579&edition=5>Job3rg_</a></td>
        <td>3</td>
        <td>9628.267</td>
        <td>706.667</td>
    </tr>
    <tr>
        <td>1291</td>
        <td><a href=players.php?pid=70393&edition=5>wrubko</a></td>
        <td>3</td>
        <td>9628.293</td>
        <td>707.333</td>
    </tr>
    <tr>
        <td>1292</td>
        <td><a href=players.php?pid=65745&edition=5><span style='color:#aaddee;font-weight:bold;'>S</span><span
                    style='color:#ffbb00;font-weight:bold;'>W</span><span
                    style='color:#0000ff;font-weight:bold;'>A</span><span
                    style='color:#ffccdd;font-weight:bold;'>G</span><span
                    style='color:#ffffff;letter-spacing: -0.1em;font-size:smaller'>ITHORR</span></a></td>
        <td>3</td>
        <td>9628.360</td>
        <td>709.000</td>
    </tr>
    <tr>
        <td>1293</td>
        <td><a href=players.php?pid=30070&edition=5>Arczi</a></td>
        <td>3</td>
        <td>9628.507</td>
        <td>712.667</td>
    </tr>
    <tr>
        <td>1294</td>
        <td><a href=players.php?pid=40130&edition=5>zack2301</a></td>
        <td>3</td>
        <td>9628.560</td>
        <td>714.000</td>
    </tr>
    <tr>
        <td>1295</td>
        <td><a href=players.php?pid=38517&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;GardeMeuble</span></a></td>
        <td>3</td>
        <td>9628.573</td>
        <td>714.333</td>
    </tr>
    <tr>
        <td>1296</td>
        <td><a href=players.php?pid=29813&edition=5>XecNu</a></td>
        <td>3</td>
        <td>9628.733</td>
        <td>718.333</td>
    </tr>
    <tr>
        <td>1297</td>
        <td><a href=players.php?pid=67421&edition=5>lukiskywalker_</a></td>
        <td>3</td>
        <td>9628.947</td>
        <td>723.667</td>
    </tr>
    <tr>
        <td>1298</td>
        <td><a href=players.php?pid=3054&edition=5>Doctor_R0ck</a></td>
        <td>3</td>
        <td>9629.080</td>
        <td>727.000</td>
    </tr>
    <tr>
        <td>1299</td>
        <td><a href=players.php?pid=66133&edition=5>lolko11</a></td>
        <td>3</td>
        <td>9629.080</td>
        <td>727.000</td>
    </tr>
    <tr>
        <td>1300</td>
        <td><a href=players.php?pid=67603&edition=5>gdx.</a></td>
        <td>3</td>
        <td>9629.227</td>
        <td>730.667</td>
    </tr>
    <tr>
        <td>1301</td>
        <td><a href=players.php?pid=48519&edition=5>LordCoopton</a></td>
        <td>3</td>
        <td>9629.280</td>
        <td>732.000</td>
    </tr>
    <tr>
        <td>1302</td>
        <td><a href=players.php?pid=1538&edition=5>Chokappa</a></td>
        <td>3</td>
        <td>9629.280</td>
        <td>732.000</td>
    </tr>
    <tr>
        <td>1303</td>
        <td><a href=players.php?pid=68578&edition=5>Levan-_-</a></td>
        <td>3</td>
        <td>9629.347</td>
        <td>733.667</td>
    </tr>
    <tr>
        <td>1304</td>
        <td><a href=players.php?pid=66665&edition=5><span style='color:#ff4455;'>G</span><span
                    style='color:#ff5566;'>4</span><span style='color:#ff6677;'>_</span><span
                    style='color:#ff7788;'>.</span><span style='color:#ff8899;'>-</span></a></td>
        <td>3</td>
        <td>9629.373</td>
        <td>734.333</td>
    </tr>
    <tr>
        <td>1305</td>
        <td><a href=players.php?pid=25764&edition=5>InariTM</a></td>
        <td>3</td>
        <td>9629.413</td>
        <td>735.333</td>
    </tr>
    <tr>
        <td>1306</td>
        <td><a href=players.php?pid=42212&edition=5>toastersau</a></td>
        <td>3</td>
        <td>9629.493</td>
        <td>737.333</td>
    </tr>
    <tr>
        <td>1307</td>
        <td><a href=players.php?pid=53089&edition=5>Don_Pojjo</a></td>
        <td>3</td>
        <td>9629.533</td>
        <td>738.333</td>
    </tr>
    <tr>
        <td>1308</td>
        <td><a href=players.php?pid=69062&edition=5>Hope.TM</a></td>
        <td>3</td>
        <td>9629.893</td>
        <td>747.333</td>
    </tr>
    <tr>
        <td>1309</td>
        <td><a href=players.php?pid=43302&edition=5><span style='color:#ffbb00;font-weight:bold;'>B</span>erttheg<span
                    style='color:#ffbb00;font-weight:bold;'>&empty;</span>rilla</a></td>
        <td>3</td>
        <td>9630.040</td>
        <td>751.000</td>
    </tr>
    <tr>
        <td>1310</td>
        <td><a href=players.php?pid=69052&edition=5>ItsLukeM2</a></td>
        <td>3</td>
        <td>9630.147</td>
        <td>753.667</td>
    </tr>
    <tr>
        <td>1311</td>
        <td><a href=players.php?pid=50063&edition=5>stronny</a></td>
        <td>3</td>
        <td>9630.293</td>
        <td>757.333</td>
    </tr>
    <tr>
        <td>1312</td>
        <td><a href=players.php?pid=53501&edition=5>b<span
                    style='color:#ff00ff;font-style:italic;'>&nbsp;POULE&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;&nbsp;KuHaKu</span></a></td>
        <td>3</td>
        <td>9630.413</td>
        <td>760.333</td>
    </tr>
    <tr>
        <td>1313</td>
        <td><a href=players.php?pid=20952&edition=5>T0kagi</a></td>
        <td>3</td>
        <td>9630.507</td>
        <td>762.667</td>
    </tr>
    <tr>
        <td>1314</td>
        <td><a href=players.php?pid=56892&edition=5>MCrusader_</a></td>
        <td>3</td>
        <td>9630.560</td>
        <td>764.000</td>
    </tr>
    <tr>
        <td>1315</td>
        <td><a href=players.php?pid=72469&edition=5>calz0r.</a></td>
        <td>3</td>
        <td>9630.640</td>
        <td>766.000</td>
    </tr>
    <tr>
        <td>1316</td>
        <td><a href=players.php?pid=22433&edition=5>TenderOpening</a></td>
        <td>3</td>
        <td>9630.653</td>
        <td>766.333</td>
    </tr>
    <tr>
        <td>1317</td>
        <td><a href=players.php?pid=46779&edition=5>Jules61</a></td>
        <td>3</td>
        <td>9630.720</td>
        <td>768.000</td>
    </tr>
    <tr>
        <td>1318</td>
        <td><a href=players.php?pid=41606&edition=5>DaGreatCake</a></td>
        <td>3</td>
        <td>9630.733</td>
        <td>768.333</td>
    </tr>
    <tr>
        <td>1319</td>
        <td><a href=players.php?pid=52787&edition=5>nLMash_</a></td>
        <td>3</td>
        <td>9630.893</td>
        <td>772.333</td>
    </tr>
    <tr>
        <td>1320</td>
        <td><a href=players.php?pid=35548&edition=5><span style='color:#ff6600;'>M</span><span
                    style='color:#ee6611;'>o</span><span style='color:#dd5511;'>r</span><span
                    style='color:#cc5522;'>i</span><span style='color:#bb5522;'>t</span><span
                    style='color:#aa5533;'>z</span><span style='color:#884433;'>_</span><span
                    style='color:#774444;'>S</span><span style='color:#664444;'>p</span><span
                    style='color:#554455;'>a</span><span style='color:#443355;'>c</span><span
                    style='color:#333366;'>e</span></a></td>
        <td>3</td>
        <td>9630.973</td>
        <td>774.333</td>
    </tr>
    <tr>
        <td>1321</td>
        <td><a href=players.php?pid=2&edition=5><span style='color:#00ff00;'>k*mochi</span></a></td>
        <td>3</td>
        <td>9631.160</td>
        <td>779.000</td>
    </tr>
    <tr>
        <td>1322</td>
        <td><a href=players.php?pid=69513&edition=5>boat</a></td>
        <td>3</td>
        <td>9631.307</td>
        <td>782.667</td>
    </tr>
    <tr>
        <td>1323</td>
        <td><a href=players.php?pid=34926&edition=5>KralBrambora</a></td>
        <td>3</td>
        <td>9631.347</td>
        <td>783.667</td>
    </tr>
    <tr>
        <td>1324</td>
        <td><a href=players.php?pid=1475&edition=5><span style='color:#ffffff;'>roxxon</span><span
                    style='color:#ffaa11;'>.иſ</span></a></td>
        <td>3</td>
        <td>9631.373</td>
        <td>784.333</td>
    </tr>
    <tr>
        <td>1325</td>
        <td><a href=players.php?pid=10768&edition=5>Matqeua</a></td>
        <td>3</td>
        <td>9631.427</td>
        <td>785.667</td>
    </tr>
    <tr>
        <td>1326</td>
        <td><a href=players.php?pid=51593&edition=5>CumuloJimbus</a></td>
        <td>3</td>
        <td>9631.507</td>
        <td>787.667</td>
    </tr>
    <tr>
        <td>1327</td>
        <td><a href=players.php?pid=33245&edition=5><span style='color:#000033;'>J</span><span
                    style='color:#220055;'>u</span><span style='color:#330088;'>l</span><span
                    style='color:#5500aa;'>1</span><span style='color:#6600cc;'>a</span><span
                    style='color:#6600cc;'>n</span><span style='color:#5500cc;'>_</span><span
                    style='color:#4400cc;'>N</span><span style='color:#3300cc;'>L</span></a></td>
        <td>3</td>
        <td>9631.707</td>
        <td>792.667</td>
    </tr>
    <tr>
        <td>1328</td>
        <td><a href=players.php?pid=8496&edition=5>Feel_Like_A-Sir</a></td>
        <td>3</td>
        <td>9631.840</td>
        <td>796.000</td>
    </tr>
    <tr>
        <td>1329</td>
        <td><a href=players.php?pid=68990&edition=5>DutchPhantom1</a></td>
        <td>3</td>
        <td>9632.013</td>
        <td>800.333</td>
    </tr>
    <tr>
        <td>1330</td>
        <td><a href=players.php?pid=7364&edition=5>Fireexodus</a></td>
        <td>3</td>
        <td>9632.067</td>
        <td>801.667</td>
    </tr>
    <tr>
        <td>1331</td>
        <td><a href=players.php?pid=51913&edition=5>PigeonSmuggler</a></td>
        <td>3</td>
        <td>9632.080</td>
        <td>802.000</td>
    </tr>
    <tr>
        <td>1332</td>
        <td><a href=players.php?pid=14882&edition=5><span style='color:#ff0000;'>N</span><span
                    style='color:#ff2211;'>i</span><span style='color:#ff4422;'>ҳ</span><span
                    style='color:#ff6633;'>&sigma;</span><span style='color:#ff6633;'>ł</span><span
                    style='color:#ff8822;'>ą</span><span style='color:#ff9900;'>&gamma;</span></a></td>
        <td>3</td>
        <td>9632.160</td>
        <td>804.000</td>
    </tr>
    <tr>
        <td>1333</td>
        <td><a href=players.php?pid=5004&edition=5>Erosiah</a></td>
        <td>3</td>
        <td>9632.187</td>
        <td>804.667</td>
    </tr>
    <tr>
        <td>1334</td>
        <td><a href=players.php?pid=68489&edition=5>Svenne1251</a></td>
        <td>3</td>
        <td>9632.200</td>
        <td>805.000</td>
    </tr>
    <tr>
        <td>1335</td>
        <td><a href=players.php?pid=68173&edition=5>Diablx123</a></td>
        <td>3</td>
        <td>9632.293</td>
        <td>807.333</td>
    </tr>
    <tr>
        <td>1336</td>
        <td><a href=players.php?pid=8387&edition=5>:peepolove:</a></td>
        <td>3</td>
        <td>9632.413</td>
        <td>810.333</td>
    </tr>
    <tr>
        <td>1337</td>
        <td><a href=players.php?pid=69619&edition=5>L0G1C_B1T</a></td>
        <td>3</td>
        <td>9632.573</td>
        <td>814.333</td>
    </tr>
    <tr>
        <td>1338</td>
        <td><a href=players.php?pid=24123&edition=5>Highlyx</a></td>
        <td>3</td>
        <td>9632.747</td>
        <td>818.667</td>
    </tr>
    <tr>
        <td>1339</td>
        <td><a href=players.php?pid=36535&edition=5>up2early</a></td>
        <td>3</td>
        <td>9632.827</td>
        <td>820.667</td>
    </tr>
    <tr>
        <td>1340</td>
        <td><a href=players.php?pid=69481&edition=5>Milkygames_NL&nbsp;diddy&nbsp;party&nbsp;invite</a></td>
        <td>3</td>
        <td>9632.880</td>
        <td>822.000</td>
    </tr>
    <tr>
        <td>1341</td>
        <td><a href=players.php?pid=30965&edition=5>YaBoyTactics</a></td>
        <td>3</td>
        <td>9633.000</td>
        <td>825.000</td>
    </tr>
    <tr>
        <td>1342</td>
        <td><a href=players.php?pid=27030&edition=5>WaFee.</a></td>
        <td>3</td>
        <td>9633.147</td>
        <td>828.667</td>
    </tr>
    <tr>
        <td>1343</td>
        <td><a href=players.php?pid=67584&edition=5>Zigarrenhai</a></td>
        <td>3</td>
        <td>9633.507</td>
        <td>837.667</td>
    </tr>
    <tr>
        <td>1344</td>
        <td><a href=players.php?pid=33922&edition=5>DeinTreter</a></td>
        <td>3</td>
        <td>9633.693</td>
        <td>842.333</td>
    </tr>
    <tr>
        <td>1345</td>
        <td><a href=players.php?pid=66602&edition=5>Boris8015</a></td>
        <td>3</td>
        <td>9633.747</td>
        <td>843.667</td>
    </tr>
    <tr>
        <td>1346</td>
        <td><a href=players.php?pid=62031&edition=5>NeonEvoker</a></td>
        <td>3</td>
        <td>9633.787</td>
        <td>844.667</td>
    </tr>
    <tr>
        <td>1347</td>
        <td><a href=players.php?pid=26441&edition=5><span style='color:#9900ff;'>P</span><span
                    style='color:#7722ff;'>l</span><span style='color:#5555ff;'>u</span><span
                    style='color:#4477ff;'>r</span><span style='color:#22aaff;'>y</span><span
                    style='color:#00ccff;'>l</span></a></td>
        <td>3</td>
        <td>9633.880</td>
        <td>847.000</td>
    </tr>
    <tr>
        <td>1348</td>
        <td><a href=players.php?pid=66650&edition=5>KaptenBirb</a></td>
        <td>3</td>
        <td>9634.013</td>
        <td>850.333</td>
    </tr>
    <tr>
        <td>1349</td>
        <td><a href=players.php?pid=34686&edition=5>Fawlix</a></td>
        <td>3</td>
        <td>9634.040</td>
        <td>851.000</td>
    </tr>
    <tr>
        <td>1350</td>
        <td><a href=players.php?pid=54996&edition=5>Gogi_Rl</a></td>
        <td>3</td>
        <td>9634.453</td>
        <td>861.333</td>
    </tr>
    <tr>
        <td>1351</td>
        <td><a href=players.php?pid=70478&edition=5>alastairrjm</a></td>
        <td>3</td>
        <td>9634.467</td>
        <td>861.667</td>
    </tr>
    <tr>
        <td>1352</td>
        <td><a href=players.php?pid=50159&edition=5>NIEBRX07</a></td>
        <td>3</td>
        <td>9634.680</td>
        <td>867.000</td>
    </tr>
    <tr>
        <td>1353</td>
        <td><a href=players.php?pid=13059&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Kirigouter</span></a></td>
        <td>3</td>
        <td>9634.693</td>
        <td>867.333</td>
    </tr>
    <tr>
        <td>1354</td>
        <td><a href=players.php?pid=67205&edition=5>DianeFoxIsMommy</a></td>
        <td>3</td>
        <td>9635.000</td>
        <td>875.000</td>
    </tr>
    <tr>
        <td>1355</td>
        <td><a href=players.php?pid=66452&edition=5>Tby313</a></td>
        <td>3</td>
        <td>9635.307</td>
        <td>882.667</td>
    </tr>
    <tr>
        <td>1356</td>
        <td><a href=players.php?pid=11060&edition=5>SESAMBROETCHEN.</a></td>
        <td>3</td>
        <td>9635.453</td>
        <td>886.333</td>
    </tr>
    <tr>
        <td>1357</td>
        <td><a href=players.php?pid=53529&edition=5>AyKu0109</a></td>
        <td>3</td>
        <td>9635.627</td>
        <td>890.667</td>
    </tr>
    <tr>
        <td>1358</td>
        <td><a href=players.php?pid=68487&edition=5>SkyrunN_</a></td>
        <td>3</td>
        <td>9636.053</td>
        <td>901.333</td>
    </tr>
    <tr>
        <td>1359</td>
        <td><a href=players.php?pid=7382&edition=5><span style='color:#0033cc;'>G</span><span
                    style='color:#1155dd;'>e</span><span style='color:#2277dd;'>r</span><span
                    style='color:#4488ee;'>r</span><span style='color:#55aaee;'>i</span><span
                    style='color:#66ccff;'>e</span></a></td>
        <td>3</td>
        <td>9636.053</td>
        <td>901.333</td>
    </tr>
    <tr>
        <td>1360</td>
        <td><a href=players.php?pid=7504&edition=5>Estophy</a></td>
        <td>3</td>
        <td>9636.253</td>
        <td>906.333</td>
    </tr>
    <tr>
        <td>1361</td>
        <td><a href=players.php?pid=29105&edition=5>Scoutbang</a></td>
        <td>3</td>
        <td>9636.293</td>
        <td>907.333</td>
    </tr>
    <tr>
        <td>1362</td>
        <td><a href=players.php?pid=54942&edition=5>b<span
                    style='color:#ff00ff;font-style:italic;'>&nbsp;POULE&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;Thicondriustf</span></a></td>
        <td>3</td>
        <td>9636.720</td>
        <td>918.000</td>
    </tr>
    <tr>
        <td>1363</td>
        <td><a href=players.php?pid=63987&edition=5>kundrum</a></td>
        <td>3</td>
        <td>9636.893</td>
        <td>922.333</td>
    </tr>
    <tr>
        <td>1364</td>
        <td><a href=players.php?pid=67887&edition=5><span style='color:#990000;'>S</span><span
                    style='color:#aa2200;'>e</span><span style='color:#bb3300;'>r</span><span
                    style='color:#cc5500;'>r</span><span style='color:#cc7700;'>i</span><span
                    style='color:#dd9900;'>c</span><span style='color:#eeaa00;'>k</span><span
                    style='color:#ffcc00;'>7</span></a></td>
        <td>3</td>
        <td>9636.893</td>
        <td>922.333</td>
    </tr>
    <tr>
        <td>1365</td>
        <td><a href=players.php?pid=37942&edition=5>Sealites</a></td>
        <td>3</td>
        <td>9636.920</td>
        <td>923.000</td>
    </tr>
    <tr>
        <td>1366</td>
        <td><a href=players.php?pid=59611&edition=5>VAAAST</a></td>
        <td>3</td>
        <td>9637.040</td>
        <td>926.000</td>
    </tr>
    <tr>
        <td>1367</td>
        <td><a href=players.php?pid=9096&edition=5>Laexus</a></td>
        <td>3</td>
        <td>9637.173</td>
        <td>929.333</td>
    </tr>
    <tr>
        <td>1368</td>
        <td><a href=players.php?pid=68449&edition=5>Epodon11</a></td>
        <td>3</td>
        <td>9637.240</td>
        <td>931.000</td>
    </tr>
    <tr>
        <td>1369</td>
        <td><a href=players.php?pid=22061&edition=5>N3cno</a></td>
        <td>3</td>
        <td>9638.573</td>
        <td>964.333</td>
    </tr>
    <tr>
        <td>1370</td>
        <td><a href=players.php?pid=2650&edition=5>YdraelVitesse</a></td>
        <td>3</td>
        <td>9638.760</td>
        <td>969.000</td>
    </tr>
    <tr>
        <td>1371</td>
        <td><a href=players.php?pid=27886&edition=5>DanielCosta1888</a></td>
        <td>3</td>
        <td>9638.787</td>
        <td>969.667</td>
    </tr>
    <tr>
        <td>1372</td>
        <td><a href=players.php?pid=46780&edition=5>Arnon994</a></td>
        <td>3</td>
        <td>9639.080</td>
        <td>977.000</td>
    </tr>
    <tr>
        <td>1373</td>
        <td><a href=players.php?pid=70297&edition=5>AuTumn69420</a></td>
        <td>3</td>
        <td>9639.360</td>
        <td>984.000</td>
    </tr>
    <tr>
        <td>1374</td>
        <td><a href=players.php?pid=43911&edition=5>Will:sadgeBusiness:Beaton</a></td>
        <td>3</td>
        <td>9639.760</td>
        <td>994.000</td>
    </tr>
    <tr>
        <td>1375</td>
        <td><a href=players.php?pid=45777&edition=5>luka42O</a></td>
        <td>3</td>
        <td>9640.107</td>
        <td>1002.667</td>
    </tr>
    <tr>
        <td>1376</td>
        <td><a href=players.php?pid=66373&edition=5><span style='color:#00ffff;font-weight:bold;'>Simensun</span></a>
        </td>
        <td>3</td>
        <td>9640.253</td>
        <td>1006.333</td>
    </tr>
    <tr>
        <td>1377</td>
        <td><a href=players.php?pid=16588&edition=5>sfighter17</a></td>
        <td>3</td>
        <td>9640.293</td>
        <td>1007.333</td>
    </tr>
    <tr>
        <td>1378</td>
        <td><a href=players.php?pid=54351&edition=5>KneecapGuy</a></td>
        <td>3</td>
        <td>9641.147</td>
        <td>1028.667</td>
    </tr>
    <tr>
        <td>1379</td>
        <td><a href=players.php?pid=65932&edition=5>GamekabouterNL</a></td>
        <td>3</td>
        <td>9641.253</td>
        <td>1031.333</td>
    </tr>
    <tr>
        <td>1380</td>
        <td><a href=players.php?pid=36855&edition=5>Gen3Champ</a></td>
        <td>3</td>
        <td>9641.600</td>
        <td>1040.000</td>
    </tr>
    <tr>
        <td>1381</td>
        <td><a href=players.php?pid=42650&edition=5><span style='color:#ff0000;'>S</span><span
                    style='color:#ee0022;'>h</span><span style='color:#cc0033;'>a</span><span
                    style='color:#cc0033;'>g</span><span style='color:#ee5522;'>o</span><span
                    style='color:#ff9900;'>o</span></a></td>
        <td>3</td>
        <td>9641.680</td>
        <td>1042.000</td>
    </tr>
    <tr>
        <td>1382</td>
        <td><a href=players.php?pid=1904&edition=5>uelv</a></td>
        <td>3</td>
        <td>9641.733</td>
        <td>1043.333</td>
    </tr>
    <tr>
        <td>1383</td>
        <td><a href=players.php?pid=52845&edition=5>Nicdaric</a></td>
        <td>3</td>
        <td>9641.947</td>
        <td>1048.667</td>
    </tr>
    <tr>
        <td>1384</td>
        <td><a href=players.php?pid=53581&edition=5>R.apid</a></td>
        <td>3</td>
        <td>9642.000</td>
        <td>1050.000</td>
    </tr>
    <tr>
        <td>1385</td>
        <td><a href=players.php?pid=48690&edition=5>jota</a></td>
        <td>3</td>
        <td>9642.347</td>
        <td>1058.667</td>
    </tr>
    <tr>
        <td>1386</td>
        <td><a href=players.php?pid=69516&edition=5>MiguelDubz</a></td>
        <td>3</td>
        <td>9642.947</td>
        <td>1073.667</td>
    </tr>
    <tr>
        <td>1387</td>
        <td><a href=players.php?pid=61027&edition=5><span style='color:#ee00bb;'>B</span><span
                    style='color:#dd00aa;'>O</span><span style='color:#dd00aa;'>U</span><span
                    style='color:#cc0099;'>G</span><span style='color:#bb0099;'>E</span></a></td>
        <td>3</td>
        <td>9643.360</td>
        <td>1084.000</td>
    </tr>
    <tr>
        <td>1388</td>
        <td><a href=players.php?pid=49899&edition=5><span style='color:#44ccdd;'>zuden</span></a></td>
        <td>3</td>
        <td>9643.907</td>
        <td>1097.667</td>
    </tr>
    <tr>
        <td>1389</td>
        <td><a href=players.php?pid=32191&edition=5><span style='color:#0000ff;'>DestroyBlader</span></a></td>
        <td>3</td>
        <td>9644.133</td>
        <td>1103.333</td>
    </tr>
    <tr>
        <td>1390</td>
        <td><a href=players.php?pid=69472&edition=5>PrAm686</a></td>
        <td>3</td>
        <td>9644.240</td>
        <td>1106.000</td>
    </tr>
    <tr>
        <td>1391</td>
        <td><a href=players.php?pid=67880&edition=5>xedrox6</a></td>
        <td>3</td>
        <td>9645.027</td>
        <td>1125.667</td>
    </tr>
    <tr>
        <td>1392</td>
        <td><a href=players.php?pid=38970&edition=5><span style='color:#ffff00;font-weight:bold;'>C</span><span
                    style='color:#eeee00;font-weight:bold;'>oo</span><span
                    style='color:#dddd00;font-weight:bold;'>le</span><span
                    style='color:#cccc00;font-weight:bold;'>B</span><span
                    style='color:#cccc00;font-weight:bold;'>a</span><span
                    style='color:#ccbb00;font-weight:bold;'>na</span><span
                    style='color:#ccaa00;font-weight:bold;'>n</span><span
                    style='color:#cc9900;font-weight:bold;'>e</span></a></td>
        <td>3</td>
        <td>9645.027</td>
        <td>1125.667</td>
    </tr>
    <tr>
        <td>1393</td>
        <td><a href=players.php?pid=67094&edition=5>Blake782</a></td>
        <td>3</td>
        <td>9649.360</td>
        <td>1234.000</td>
    </tr>
    <tr>
        <td>1394</td>
        <td><a href=players.php?pid=33291&edition=5>jeanjette</a></td>
        <td>3</td>
        <td>9650.427</td>
        <td>1260.667</td>
    </tr>
    <tr>
        <td>1395</td>
        <td><a href=players.php?pid=57636&edition=5>Toden_</a></td>
        <td>3</td>
        <td>9651.187</td>
        <td>1279.667</td>
    </tr>
    <tr>
        <td>1396</td>
        <td><a href=players.php?pid=67009&edition=5>Skrysia</a></td>
        <td>3</td>
        <td>9651.880</td>
        <td>1297.000</td>
    </tr>
    <tr>
        <td>1397</td>
        <td><a href=players.php?pid=70446&edition=5>l2p_Aladin</a></td>
        <td>2</td>
        <td>9734.627</td>
        <td>48.500</td>
    </tr>
    <tr>
        <td>1398</td>
        <td><a href=players.php?pid=48782&edition=5><span style='color:#ff9900;'>Mat</span><span
                    style='color:#ff9900;'>iiz</span></a></td>
        <td>2</td>
        <td>9734.813</td>
        <td>55.500</td>
    </tr>
    <tr>
        <td>1399</td>
        <td><a href=players.php?pid=66182&edition=5>BrigitteSux</a></td>
        <td>2</td>
        <td>9735.000</td>
        <td>62.500</td>
    </tr>
    <tr>
        <td>1400</td>
        <td><a href=players.php?pid=19599&edition=5><span style='color:#00ffff;'>ŧ</span><span
                    style='color:#55ffff;'>ѻ</span><span style='color:#aaffff;'>đ</span><span
                    style='color:#ffffff;'>ə</span><span style='color:#ffffff;'>я</span><span
                    style='color:#bbffff;'>ษ</span><span style='color:#66ffff;'>ǖ</span></a></td>
        <td>2</td>
        <td>9735.800</td>
        <td>92.500</td>
    </tr>
    <tr>
        <td>1401</td>
        <td><a href=players.php?pid=37153&edition=5>myr-12</a></td>
        <td>2</td>
        <td>9735.880</td>
        <td>95.500</td>
    </tr>
    <tr>
        <td>1402</td>
        <td><a href=players.php?pid=69620&edition=5>DjayCRich</a></td>
        <td>2</td>
        <td>9735.907</td>
        <td>96.500</td>
    </tr>
    <tr>
        <td>1403</td>
        <td><a href=players.php?pid=1511&edition=5>linkTM_</a></td>
        <td>2</td>
        <td>9735.933</td>
        <td>97.500</td>
    </tr>
    <tr>
        <td>1404</td>
        <td><a href=players.php?pid=65214&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Zorglub</span></a></td>
        <td>2</td>
        <td>9736.027</td>
        <td>101.000</td>
    </tr>
    <tr>
        <td>1405</td>
        <td><a href=players.php?pid=7374&edition=5>Tovarenn</a></td>
        <td>2</td>
        <td>9736.080</td>
        <td>103.000</td>
    </tr>
    <tr>
        <td>1406</td>
        <td><a href=players.php?pid=68926&edition=5>BigPillow12</a></td>
        <td>2</td>
        <td>9736.080</td>
        <td>103.000</td>
    </tr>
    <tr>
        <td>1407</td>
        <td><a href=players.php?pid=39032&edition=5>viktor8D</a></td>
        <td>2</td>
        <td>9736.147</td>
        <td>105.500</td>
    </tr>
    <tr>
        <td>1408</td>
        <td><a href=players.php?pid=71514&edition=5>Tombikass</a></td>
        <td>2</td>
        <td>9736.440</td>
        <td>116.500</td>
    </tr>
    <tr>
        <td>1409</td>
        <td><a href=players.php?pid=68457&edition=5>Saberwolf98</a></td>
        <td>2</td>
        <td>9736.520</td>
        <td>119.500</td>
    </tr>
    <tr>
        <td>1410</td>
        <td><a href=players.php?pid=5153&edition=5>Peksujeffi</a></td>
        <td>2</td>
        <td>9736.640</td>
        <td>124.000</td>
    </tr>
    <tr>
        <td>1411</td>
        <td><a href=players.php?pid=6213&edition=5>:kekw:</a></td>
        <td>2</td>
        <td>9737.267</td>
        <td>147.500</td>
    </tr>
    <tr>
        <td>1412</td>
        <td><a href=players.php?pid=57100&edition=5>zennyboy22</a></td>
        <td>2</td>
        <td>9737.280</td>
        <td>148.000</td>
    </tr>
    <tr>
        <td>1413</td>
        <td><a href=players.php?pid=39125&edition=5>Ruurd_h</a></td>
        <td>2</td>
        <td>9737.333</td>
        <td>150.000</td>
    </tr>
    <tr>
        <td>1414</td>
        <td><a href=players.php?pid=8963&edition=5>mirbs.mud</a></td>
        <td>2</td>
        <td>9737.520</td>
        <td>157.000</td>
    </tr>
    <tr>
        <td>1415</td>
        <td><a href=players.php?pid=66946&edition=5>DemosTM</a></td>
        <td>2</td>
        <td>9737.840</td>
        <td>169.000</td>
    </tr>
    <tr>
        <td>1416</td>
        <td><a href=players.php?pid=21&edition=5><span style='color:#ff00ff;font-weight:bold;'></span><span
                    style='color:#ff3399;font-weight:bold;'>&nbsp;</span><span
                    style='color:#ff6666;font-style:italic;font-weight:bold;'>d</span><span
                    style='color:#ff5577;font-style:italic;font-weight:bold;'>r</span><span
                    style='color:#ff5588;font-style:italic;font-weight:bold;'>a</span><span
                    style='color:#ff4488;font-style:italic;font-weight:bold;'>g</span><span
                    style='color:#ff3399;font-style:italic;font-weight:bold;'>o</span><span
                    style='color:#ff22aa;font-style:italic;font-weight:bold;'>n</span><span
                    style='color:#ff22bb;font-style:italic;font-weight:bold;'>p</span><span
                    style='color:#ff11bb;font-style:italic;font-weight:bold;'>n</span><span
                    style='color:#ff00cc;font-style:italic;font-weight:bold;'>tm&nbsp;[Cheese&nbsp;Police]</span></a>
        </td>
        <td>2</td>
        <td>9737.893</td>
        <td>171.000</td>
    </tr>
    <tr>
        <td>1417</td>
        <td><a href=players.php?pid=70848&edition=5>Karim_Ziani</a></td>
        <td>2</td>
        <td>9738.000</td>
        <td>175.000</td>
    </tr>
    <tr>
        <td>1418</td>
        <td><a href=players.php?pid=48243&edition=5>KeenZorse</a></td>
        <td>2</td>
        <td>9738.093</td>
        <td>178.500</td>
    </tr>
    <tr>
        <td>1419</td>
        <td><a href=players.php?pid=17026&edition=5>C.L.A.M</a></td>
        <td>2</td>
        <td>9738.107</td>
        <td>179.000</td>
    </tr>
    <tr>
        <td>1420</td>
        <td><a href=players.php?pid=66176&edition=5>ginoar8888</a></td>
        <td>2</td>
        <td>9738.147</td>
        <td>180.500</td>
    </tr>
    <tr>
        <td>1421</td>
        <td><a href=players.php?pid=62371&edition=5>Zsiblings</a></td>
        <td>2</td>
        <td>9738.187</td>
        <td>182.000</td>
    </tr>
    <tr>
        <td>1422</td>
        <td><a href=players.php?pid=62253&edition=5>Samsquanch_TM</a></td>
        <td>2</td>
        <td>9738.533</td>
        <td>195.000</td>
    </tr>
    <tr>
        <td>1423</td>
        <td><a href=players.php?pid=2483&edition=5><span style='color:#ff0000;font-weight:bold;'>S</span><span
                    style='color:#ff4444;font-weight:bold;'>k</span><span
                    style='color:#ff6666;font-weight:bold;'>yw</span><span
                    style='color:#ff8888;font-weight:bold;'>a</span><span
                    style='color:#ffbbbb;font-weight:bold;'>l</span><span
                    style='color:#ffdddd;font-weight:bold;'>k</span><span
                    style='color:#ffbbbb;font-weight:bold;'>e</span><span
                    style='color:#ff8888;font-weight:bold;'>r</span><span
                    style='color:#ff6666;font-weight:bold;'>t</span><span
                    style='color:#ff6666;font-weight:bold;'>r</span><span
                    style='color:#ff4444;font-weight:bold;'>e</span><span
                    style='color:#ff0000;font-weight:bold;'>m</span></a></td>
        <td>2</td>
        <td>9738.587</td>
        <td>197.000</td>
    </tr>
    <tr>
        <td>1424</td>
        <td><a href=players.php?pid=66457&edition=5>davymo19</a></td>
        <td>2</td>
        <td>9738.827</td>
        <td>206.000</td>
    </tr>
    <tr>
        <td>1425</td>
        <td><a href=players.php?pid=65755&edition=5>COUCHsander</a></td>
        <td>2</td>
        <td>9739.160</td>
        <td>218.500</td>
    </tr>
    <tr>
        <td>1426</td>
        <td><a href=players.php?pid=59564&edition=5>DripOrDrown911</a></td>
        <td>2</td>
        <td>9739.160</td>
        <td>218.500</td>
    </tr>
    <tr>
        <td>1427</td>
        <td><a href=players.php?pid=115&edition=5>donadigo</a></td>
        <td>2</td>
        <td>9739.373</td>
        <td>226.500</td>
    </tr>
    <tr>
        <td>1428</td>
        <td><a href=players.php?pid=68098&edition=5>JonElephant_TM</a></td>
        <td>2</td>
        <td>9739.440</td>
        <td>229.000</td>
    </tr>
    <tr>
        <td>1429</td>
        <td><a href=players.php?pid=67374&edition=5><span style='color:#8822bb;'>H</span><span
                    style='color:#5555cc;'>o</span><span style='color:#3399ee;'>p</span><span
                    style='color:#00ccff;'>n</span><span style='color:#00ccff;'>u</span><span
                    style='color:#4477dd;'>l</span><span style='color:#8822bb;'>l</span></a></td>
        <td>2</td>
        <td>9739.560</td>
        <td>233.500</td>
    </tr>
    <tr>
        <td>1430</td>
        <td><a href=players.php?pid=53133&edition=5>PhantomInfinity</a></td>
        <td>2</td>
        <td>9739.667</td>
        <td>237.500</td>
    </tr>
    <tr>
        <td>1431</td>
        <td><a href=players.php?pid=60468&edition=5>riojohnston1432</a></td>
        <td>2</td>
        <td>9740.027</td>
        <td>251.000</td>
    </tr>
    <tr>
        <td>1432</td>
        <td><a href=players.php?pid=69454&edition=5>Wabbo</a></td>
        <td>2</td>
        <td>9740.160</td>
        <td>256.000</td>
    </tr>
    <tr>
        <td>1433</td>
        <td><a href=players.php?pid=3212&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span
                    style='color:#000000;font-style:italic;'>P</span><span
                    style='color:#333333;font-style:italic;'>l</span><span
                    style='color:#555555;font-style:italic;'>a</span><span
                    style='color:#888888;font-style:italic;'>t</span><span
                    style='color:#aaaaaa;font-style:italic;'>y&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>シ</span></a></td>
        <td>2</td>
        <td>9740.173</td>
        <td>256.500</td>
    </tr>
    <tr>
        <td>1434</td>
        <td><a href=players.php?pid=68838&edition=5>Crowler01</a></td>
        <td>2</td>
        <td>9740.187</td>
        <td>257.000</td>
    </tr>
    <tr>
        <td>1435</td>
        <td><a href=players.php?pid=56566&edition=5>taokai</a></td>
        <td>2</td>
        <td>9740.240</td>
        <td>259.000</td>
    </tr>
    <tr>
        <td>1436</td>
        <td><a href=players.php?pid=67387&edition=5>fdkle</a></td>
        <td>2</td>
        <td>9740.280</td>
        <td>260.500</td>
    </tr>
    <tr>
        <td>1437</td>
        <td><a href=players.php?pid=67411&edition=5>Otab45</a></td>
        <td>2</td>
        <td>9740.427</td>
        <td>266.000</td>
    </tr>
    <tr>
        <td>1438</td>
        <td><a href=players.php?pid=69000&edition=5>FuRin0223</a></td>
        <td>2</td>
        <td>9740.467</td>
        <td>267.500</td>
    </tr>
    <tr>
        <td>1439</td>
        <td><a href=players.php?pid=46467&edition=5><span style='font-weight:bold;'>&Dagger;</span><span
                    style='color:#9922aa;font-weight:bold;'>komfona</span><span
                    style='color:#000000;font-weight:bold;'>&Dagger;</span></a></td>
        <td>2</td>
        <td>9740.587</td>
        <td>272.000</td>
    </tr>
    <tr>
        <td>1440</td>
        <td><a href=players.php?pid=40284&edition=5><span style='color:#66ffcc;'>N</span><span
                    style='color:#44bbcc;'>o</span><span style='color:#2277cc;'>x</span><span
                    style='color:#0033cc;'>i</span></a></td>
        <td>2</td>
        <td>9740.773</td>
        <td>279.000</td>
    </tr>
    <tr>
        <td>1441</td>
        <td><a href=players.php?pid=9132&edition=5>Alfadream00</a></td>
        <td>2</td>
        <td>9740.800</td>
        <td>280.000</td>
    </tr>
    <tr>
        <td>1442</td>
        <td><a href=players.php?pid=31346&edition=5><span style='color:#ff9933;'>N</span><span
                    style='color:#ee9944;'>o</span><span style='color:#cc8855;'>T</span><span
                    style='color:#bb8877;'>_</span><span style='color:#998888;'>L</span><span
                    style='color:#888899;'>u</span><span style='color:#6677aa;'>c</span><span
                    style='color:#5577bb;'>k</span><span style='color:#3377dd;'>i</span><span
                    style='color:#2266ee;'>i</span><span style='color:#0066ff;'>i</span></a></td>
        <td>2</td>
        <td>9740.907</td>
        <td>284.000</td>
    </tr>
    <tr>
        <td>1443</td>
        <td><a href=players.php?pid=66852&edition=5>Linus7661</a></td>
        <td>2</td>
        <td>9741.067</td>
        <td>290.000</td>
    </tr>
    <tr>
        <td>1444</td>
        <td><a href=players.php?pid=63149&edition=5>Nilr0ss</a></td>
        <td>2</td>
        <td>9741.107</td>
        <td>291.500</td>
    </tr>
    <tr>
        <td>1445</td>
        <td><a href=players.php?pid=33227&edition=5>Ouffrobi</a></td>
        <td>2</td>
        <td>9741.347</td>
        <td>300.500</td>
    </tr>
    <tr>
        <td>1446</td>
        <td><a href=players.php?pid=67602&edition=5>rndmnb</a></td>
        <td>2</td>
        <td>9741.400</td>
        <td>302.500</td>
    </tr>
    <tr>
        <td>1447</td>
        <td><a href=players.php?pid=66595&edition=5>DrPepper_MD</a></td>
        <td>2</td>
        <td>9741.413</td>
        <td>303.000</td>
    </tr>
    <tr>
        <td>1448</td>
        <td><a href=players.php?pid=44923&edition=5>Laysen_Red</a></td>
        <td>2</td>
        <td>9741.507</td>
        <td>306.500</td>
    </tr>
    <tr>
        <td>1449</td>
        <td><a href=players.php?pid=2433&edition=5>wiskyllers</a></td>
        <td>2</td>
        <td>9741.533</td>
        <td>307.500</td>
    </tr>
    <tr>
        <td>1450</td>
        <td><a href=players.php?pid=69518&edition=5>Prepkart</a></td>
        <td>2</td>
        <td>9741.533</td>
        <td>307.500</td>
    </tr>
    <tr>
        <td>1451</td>
        <td><a href=players.php?pid=15697&edition=5>SmakzZ44</a></td>
        <td>2</td>
        <td>9741.587</td>
        <td>309.500</td>
    </tr>
    <tr>
        <td>1452</td>
        <td><a href=players.php?pid=34653&edition=5>speedrunner346</a></td>
        <td>2</td>
        <td>9741.720</td>
        <td>314.500</td>
    </tr>
    <tr>
        <td>1453</td>
        <td><a href=players.php?pid=53128&edition=5>Ravenclaw171</a></td>
        <td>2</td>
        <td>9741.733</td>
        <td>315.000</td>
    </tr>
    <tr>
        <td>1454</td>
        <td><a href=players.php?pid=10134&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ff6600;'>|&nbsp;</span><span style='font-style:italic;'>Bayron</span><span
                    style='color:#ff6600;font-style:italic;'>'</span></a></td>
        <td>2</td>
        <td>9741.747</td>
        <td>315.500</td>
    </tr>
    <tr>
        <td>1455</td>
        <td><a href=players.php?pid=63639&edition=5>DaTrixTM</a></td>
        <td>2</td>
        <td>9741.880</td>
        <td>320.500</td>
    </tr>
    <tr>
        <td>1456</td>
        <td><a href=players.php?pid=869&edition=5><span style='color:#3300cc;'>Jab</span><span
                    style='color:#ffdd11;'>TM</span></a></td>
        <td>2</td>
        <td>9742.040</td>
        <td>326.500</td>
    </tr>
    <tr>
        <td>1457</td>
        <td><a href=players.php?pid=67499&edition=5><span style='color:#00ccff;'>T</span><span
                    style='color:#2299ff;'>a</span><span style='color:#4466ff;'>s</span><span
                    style='color:#6633ff;'>t</span><span style='color:#7700ff;'>y</span></a></td>
        <td>2</td>
        <td>9742.080</td>
        <td>328.000</td>
    </tr>
    <tr>
        <td>1458</td>
        <td><a href=players.php?pid=28479&edition=5><span style='color:#000000;'>N</span><span
                    style='color:#110000;'>i</span><span style='color:#330011;'>g</span><span
                    style='color:#440011;'>h</span><span style='color:#660011;'>t</span><span
                    style='color:#771122;'>r</span><span style='color:#991122;'>o</span><span
                    style='color:#aa1122;'>a</span><span style='color:#cc1133;'>s</span><span
                    style='color:#dd1133;'>t</span></a></td>
        <td>2</td>
        <td>9742.107</td>
        <td>329.000</td>
    </tr>
    <tr>
        <td>1459</td>
        <td><a href=players.php?pid=3278&edition=5>CarJ</a></td>
        <td>2</td>
        <td>9742.560</td>
        <td>346.000</td>
    </tr>
    <tr>
        <td>1460</td>
        <td><a href=players.php?pid=1808&edition=5>Kennemayne</a></td>
        <td>2</td>
        <td>9742.587</td>
        <td>347.000</td>
    </tr>
    <tr>
        <td>1461</td>
        <td><a href=players.php?pid=72283&edition=5>Jedsed</a></td>
        <td>2</td>
        <td>9742.627</td>
        <td>348.500</td>
    </tr>
    <tr>
        <td>1462</td>
        <td><a href=players.php?pid=68446&edition=5>Rammicus</a></td>
        <td>2</td>
        <td>9742.667</td>
        <td>350.000</td>
    </tr>
    <tr>
        <td>1463</td>
        <td><a href=players.php?pid=23405&edition=5>MethKhos</a></td>
        <td>2</td>
        <td>9742.720</td>
        <td>352.000</td>
    </tr>
    <tr>
        <td>1464</td>
        <td><a href=players.php?pid=68721&edition=5>andyb0y99</a></td>
        <td>2</td>
        <td>9742.747</td>
        <td>353.000</td>
    </tr>
    <tr>
        <td>1465</td>
        <td><a href=players.php?pid=56033&edition=5>savagemaxking</a></td>
        <td>2</td>
        <td>9742.747</td>
        <td>353.000</td>
    </tr>
    <tr>
        <td>1466</td>
        <td><a href=players.php?pid=69640&edition=5>EzraXXL</a></td>
        <td>2</td>
        <td>9742.840</td>
        <td>356.500</td>
    </tr>
    <tr>
        <td>1467</td>
        <td><a href=players.php?pid=12053&edition=5>Liverstime</a></td>
        <td>2</td>
        <td>9742.933</td>
        <td>360.000</td>
    </tr>
    <tr>
        <td>1468</td>
        <td><a href=players.php?pid=66173&edition=5>Dingledoofus3</a></td>
        <td>2</td>
        <td>9742.960</td>
        <td>361.000</td>
    </tr>
    <tr>
        <td>1469</td>
        <td><a href=players.php?pid=30312&edition=5>show_feet</a></td>
        <td>2</td>
        <td>9743.013</td>
        <td>363.000</td>
    </tr>
    <tr>
        <td>1470</td>
        <td><a href=players.php?pid=48392&edition=5>DarkiHeal</a></td>
        <td>2</td>
        <td>9743.067</td>
        <td>365.000</td>
    </tr>
    <tr>
        <td>1471</td>
        <td><a href=players.php?pid=48203&edition=5>Korven.TM</a></td>
        <td>2</td>
        <td>9743.200</td>
        <td>370.000</td>
    </tr>
    <tr>
        <td>1472</td>
        <td><a href=players.php?pid=34990&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>&nbsp;Spiral</span></a>
        </td>
        <td>2</td>
        <td>9743.413</td>
        <td>378.000</td>
    </tr>
    <tr>
        <td>1473</td>
        <td><a href=players.php?pid=32443&edition=5>FABIOROWO-TM</a></td>
        <td>2</td>
        <td>9743.613</td>
        <td>385.500</td>
    </tr>
    <tr>
        <td>1474</td>
        <td><a href=players.php?pid=35855&edition=5>Smaouls</a></td>
        <td>2</td>
        <td>9743.667</td>
        <td>387.500</td>
    </tr>
    <tr>
        <td>1475</td>
        <td><a href=players.php?pid=71280&edition=5>Cazou21</a></td>
        <td>2</td>
        <td>9743.840</td>
        <td>394.000</td>
    </tr>
    <tr>
        <td>1476</td>
        <td><a href=players.php?pid=53970&edition=5>noaw.</a></td>
        <td>2</td>
        <td>9743.920</td>
        <td>397.000</td>
    </tr>
    <tr>
        <td>1477</td>
        <td><a href=players.php?pid=55035&edition=5>Noshikki_TV</a></td>
        <td>2</td>
        <td>9743.960</td>
        <td>398.500</td>
    </tr>
    <tr>
        <td>1478</td>
        <td><a href=players.php?pid=55653&edition=5>FancyFroggy</a></td>
        <td>2</td>
        <td>9744.013</td>
        <td>400.500</td>
    </tr>
    <tr>
        <td>1479</td>
        <td><a href=players.php?pid=48830&edition=5>AndreSav14</a></td>
        <td>2</td>
        <td>9744.120</td>
        <td>404.500</td>
    </tr>
    <tr>
        <td>1480</td>
        <td><a href=players.php?pid=25029&edition=5>I00p3n4</a></td>
        <td>2</td>
        <td>9744.147</td>
        <td>405.500</td>
    </tr>
    <tr>
        <td>1481</td>
        <td><a href=players.php?pid=3947&edition=5>Bulcain</a></td>
        <td>2</td>
        <td>9744.187</td>
        <td>407.000</td>
    </tr>
    <tr>
        <td>1482</td>
        <td><a href=players.php?pid=28258&edition=5>Smullie</a></td>
        <td>2</td>
        <td>9744.280</td>
        <td>410.500</td>
    </tr>
    <tr>
        <td>1483</td>
        <td><a href=players.php?pid=62773&edition=5>scheepsjongen</a></td>
        <td>2</td>
        <td>9744.587</td>
        <td>422.000</td>
    </tr>
    <tr>
        <td>1484</td>
        <td><a href=players.php?pid=4430&edition=5>WarL_TM</a></td>
        <td>2</td>
        <td>9744.600</td>
        <td>422.500</td>
    </tr>
    <tr>
        <td>1485</td>
        <td><a href=players.php?pid=57224&edition=5>Diojii</a></td>
        <td>2</td>
        <td>9744.613</td>
        <td>423.000</td>
    </tr>
    <tr>
        <td>1486</td>
        <td><a href=players.php?pid=1271&edition=5>ziberty_TM</a></td>
        <td>2</td>
        <td>9744.667</td>
        <td>425.000</td>
    </tr>
    <tr>
        <td>1487</td>
        <td><a href=players.php?pid=10000&edition=5>j.zzz</a></td>
        <td>2</td>
        <td>9744.693</td>
        <td>426.000</td>
    </tr>
    <tr>
        <td>1488</td>
        <td><a href=players.php?pid=20630&edition=5>r4z0r66</a></td>
        <td>2</td>
        <td>9744.893</td>
        <td>433.500</td>
    </tr>
    <tr>
        <td>1489</td>
        <td><a href=players.php?pid=35185&edition=5>Houston..</a></td>
        <td>2</td>
        <td>9744.907</td>
        <td>434.000</td>
    </tr>
    <tr>
        <td>1490</td>
        <td><a href=players.php?pid=51785&edition=5>ClusjRL</a></td>
        <td>2</td>
        <td>9744.947</td>
        <td>435.500</td>
    </tr>
    <tr>
        <td>1491</td>
        <td><a href=players.php?pid=26426&edition=5>zen_753</a></td>
        <td>2</td>
        <td>9744.960</td>
        <td>436.000</td>
    </tr>
    <tr>
        <td>1492</td>
        <td><a href=players.php?pid=31015&edition=5>Allexx_</a></td>
        <td>2</td>
        <td>9744.960</td>
        <td>436.000</td>
    </tr>
    <tr>
        <td>1493</td>
        <td><a href=players.php?pid=51975&edition=5>Liffy93</a></td>
        <td>2</td>
        <td>9744.987</td>
        <td>437.000</td>
    </tr>
    <tr>
        <td>1494</td>
        <td><a href=players.php?pid=71142&edition=5>ItsASquare</a></td>
        <td>2</td>
        <td>9745.093</td>
        <td>441.000</td>
    </tr>
    <tr>
        <td>1495</td>
        <td><a href=players.php?pid=35478&edition=5>CrazyLoonitic55</a></td>
        <td>2</td>
        <td>9745.147</td>
        <td>443.000</td>
    </tr>
    <tr>
        <td>1496</td>
        <td><a href=players.php?pid=11513&edition=5>Pastoor1</a></td>
        <td>2</td>
        <td>9745.200</td>
        <td>445.000</td>
    </tr>
    <tr>
        <td>1497</td>
        <td><a href=players.php?pid=39288&edition=5><span style='color:#cc3300;font-style:italic;'>&tau;гy</span><span
                    style='color:#778899;font-style:italic;'>.</span><span
                    style='color:#ffffff;font-style:italic;'>Wakes</span></a></td>
        <td>2</td>
        <td>9745.307</td>
        <td>449.000</td>
    </tr>
    <tr>
        <td>1498</td>
        <td><a href=players.php?pid=69298&edition=5>Eklair133</a></td>
        <td>2</td>
        <td>9745.333</td>
        <td>450.000</td>
    </tr>
    <tr>
        <td>1499</td>
        <td><a href=players.php?pid=67523&edition=5>Kamilus5566</a></td>
        <td>2</td>
        <td>9745.333</td>
        <td>450.000</td>
    </tr>
    <tr>
        <td>1500</td>
        <td><a href=players.php?pid=64482&edition=5>TheSkier1936</a></td>
        <td>2</td>
        <td>9745.587</td>
        <td>459.500</td>
    </tr>
    <tr>
        <td>1501</td>
        <td><a href=players.php?pid=9140&edition=5>AlexieJr</a></td>
        <td>2</td>
        <td>9745.707</td>
        <td>464.000</td>
    </tr>
    <tr>
        <td>1502</td>
        <td><a href=players.php?pid=55716&edition=5>SimSiiii</a></td>
        <td>2</td>
        <td>9745.773</td>
        <td>466.500</td>
    </tr>
    <tr>
        <td>1503</td>
        <td><a href=players.php?pid=66698&edition=5>LeondaSky</a></td>
        <td>2</td>
        <td>9745.867</td>
        <td>470.000</td>
    </tr>
    <tr>
        <td>1504</td>
        <td><a href=players.php?pid=22146&edition=5>SporeZeroX</a></td>
        <td>2</td>
        <td>9745.920</td>
        <td>472.000</td>
    </tr>
    <tr>
        <td>1505</td>
        <td><a href=players.php?pid=33741&edition=5>aScaredTortoise</a></td>
        <td>2</td>
        <td>9745.933</td>
        <td>472.500</td>
    </tr>
    <tr>
        <td>1506</td>
        <td><a href=players.php?pid=41641&edition=5>zKoro_z</a></td>
        <td>2</td>
        <td>9746.093</td>
        <td>478.500</td>
    </tr>
    <tr>
        <td>1507</td>
        <td><a href=players.php?pid=8162&edition=5>SuperBekaa</a></td>
        <td>2</td>
        <td>9746.107</td>
        <td>479.000</td>
    </tr>
    <tr>
        <td>1508</td>
        <td><a href=players.php?pid=61674&edition=5>ThijnHD</a></td>
        <td>2</td>
        <td>9746.133</td>
        <td>480.000</td>
    </tr>
    <tr>
        <td>1509</td>
        <td><a href=players.php?pid=53534&edition=5>inkunuga</a></td>
        <td>2</td>
        <td>9746.147</td>
        <td>480.500</td>
    </tr>
    <tr>
        <td>1510</td>
        <td><a href=players.php?pid=42416&edition=5><span style='color:#0099ff;'>Gu</span><span
                    style='color:#11aaee;'>bby</span><span style='color:#22bbdd;'>gam</span><span
                    style='color:#33cccc;'>er</span></a></td>
        <td>2</td>
        <td>9746.147</td>
        <td>480.500</td>
    </tr>
    <tr>
        <td>1511</td>
        <td><a href=players.php?pid=70215&edition=5>Zenucks</a></td>
        <td>2</td>
        <td>9746.267</td>
        <td>485.000</td>
    </tr>
    <tr>
        <td>1512</td>
        <td><a href=players.php?pid=2202&edition=5>Knyntsje</a></td>
        <td>2</td>
        <td>9746.347</td>
        <td>488.000</td>
    </tr>
    <tr>
        <td>1513</td>
        <td><a href=players.php?pid=32153&edition=5>Ks_TM</a></td>
        <td>2</td>
        <td>9746.347</td>
        <td>488.000</td>
    </tr>
    <tr>
        <td>1514</td>
        <td><a href=players.php?pid=719&edition=5>Romain.TM</a></td>
        <td>2</td>
        <td>9746.360</td>
        <td>488.500</td>
    </tr>
    <tr>
        <td>1515</td>
        <td><a href=players.php?pid=72782&edition=5>Sneasnar</a></td>
        <td>2</td>
        <td>9746.533</td>
        <td>495.000</td>
    </tr>
    <tr>
        <td>1516</td>
        <td><a href=players.php?pid=30110&edition=5>Zubzero1234</a></td>
        <td>2</td>
        <td>9746.560</td>
        <td>496.000</td>
    </tr>
    <tr>
        <td>1517</td>
        <td><a href=players.php?pid=12729&edition=5>Fella_TM</a></td>
        <td>2</td>
        <td>9746.573</td>
        <td>496.500</td>
    </tr>
    <tr>
        <td>1518</td>
        <td><a href=players.php?pid=41959&edition=5>Enderboy_Eli</a></td>
        <td>2</td>
        <td>9746.627</td>
        <td>498.500</td>
    </tr>
    <tr>
        <td>1519</td>
        <td><a href=players.php?pid=13469&edition=5>Laykityo</a></td>
        <td>2</td>
        <td>9746.640</td>
        <td>499.000</td>
    </tr>
    <tr>
        <td>1520</td>
        <td><a href=players.php?pid=6781&edition=5><span style='color:#ffffff;'>&alpha;&iota;г</span><span
                    style='color:#777777;'>&nbsp;ı|ı&nbsp;</span><span
                    style='color:#0077ff;font-weight:bold;'>Ҟ&Pi;&para;&reg;</span></a></td>
        <td>2</td>
        <td>9746.653</td>
        <td>499.500</td>
    </tr>
    <tr>
        <td>1521</td>
        <td><a href=players.php?pid=71302&edition=5>DearKed</a></td>
        <td>2</td>
        <td>9746.733</td>
        <td>502.500</td>
    </tr>
    <tr>
        <td>1522</td>
        <td><a href=players.php?pid=67271&edition=5>battelwolfy</a></td>
        <td>2</td>
        <td>9746.853</td>
        <td>507.000</td>
    </tr>
    <tr>
        <td>1523</td>
        <td><a href=players.php?pid=63535&edition=5>Mando558</a></td>
        <td>2</td>
        <td>9746.907</td>
        <td>509.000</td>
    </tr>
    <tr>
        <td>1524</td>
        <td><a href=players.php?pid=65822&edition=5>Misterwolfys</a></td>
        <td>2</td>
        <td>9746.973</td>
        <td>511.500</td>
    </tr>
    <tr>
        <td>1525</td>
        <td><a href=players.php?pid=34243&edition=5><span style='color:#990033;'>tuffghost</span></a></td>
        <td>2</td>
        <td>9747.053</td>
        <td>514.500</td>
    </tr>
    <tr>
        <td>1526</td>
        <td><a href=players.php?pid=66824&edition=5>Bonifatiuz</a></td>
        <td>2</td>
        <td>9747.133</td>
        <td>517.500</td>
    </tr>
    <tr>
        <td>1527</td>
        <td><a href=players.php?pid=67531&edition=5>Pfesserkoning</a></td>
        <td>2</td>
        <td>9747.147</td>
        <td>518.000</td>
    </tr>
    <tr>
        <td>1528</td>
        <td><a href=players.php?pid=68537&edition=5>Foxfire_</a></td>
        <td>2</td>
        <td>9747.160</td>
        <td>518.500</td>
    </tr>
    <tr>
        <td>1529</td>
        <td><a href=players.php?pid=35670&edition=5>jordontm</a></td>
        <td>2</td>
        <td>9747.253</td>
        <td>522.000</td>
    </tr>
    <tr>
        <td>1530</td>
        <td><a href=players.php?pid=54812&edition=5>Logofinn</a></td>
        <td>2</td>
        <td>9747.493</td>
        <td>531.000</td>
    </tr>
    <tr>
        <td>1531</td>
        <td><a href=players.php?pid=67105&edition=5>thatoneguy554</a></td>
        <td>2</td>
        <td>9747.493</td>
        <td>531.000</td>
    </tr>
    <tr>
        <td>1532</td>
        <td><a href=players.php?pid=68368&edition=5><span style='color:#ffffff;'>E</span><span
                    style='color:#ffeeff;'>l&nbsp;</span><span style='color:#ffddff;'>Nu</span><span
                    style='color:#ffccff;'>y</span><span style='color:#ffccff;'>a</span><span
                    style='color:#ffbbee;'>&nbsp;L</span><span style='color:#ffaadd;'>in</span><span
                    style='color:#ff99cc;'>a</span></a></td>
        <td>2</td>
        <td>9747.520</td>
        <td>532.000</td>
    </tr>
    <tr>
        <td>1533</td>
        <td><a href=players.php?pid=38332&edition=5><span style='color:#990033;'>E</span><span
                    style='color:#990088;'>i</span><span style='color:#9900cc;'>v</span></a></td>
        <td>2</td>
        <td>9747.520</td>
        <td>532.000</td>
    </tr>
    <tr>
        <td>1534</td>
        <td><a href=players.php?pid=30805&edition=5>iSayous</a></td>
        <td>2</td>
        <td>9747.533</td>
        <td>532.500</td>
    </tr>
    <tr>
        <td>1535</td>
        <td><a href=players.php?pid=72161&edition=5>Unkn0wnP4ssengr</a></td>
        <td>2</td>
        <td>9747.547</td>
        <td>533.000</td>
    </tr>
    <tr>
        <td>1536</td>
        <td><a href=players.php?pid=20139&edition=5>Burni-</a></td>
        <td>2</td>
        <td>9747.707</td>
        <td>539.000</td>
    </tr>
    <tr>
        <td>1537</td>
        <td><a href=players.php?pid=31908&edition=5><span style='color:#66ffff;'>Uniikz04</span></a></td>
        <td>2</td>
        <td>9747.800</td>
        <td>542.500</td>
    </tr>
    <tr>
        <td>1538</td>
        <td><a href=players.php?pid=62473&edition=5>UNO_TM</a></td>
        <td>2</td>
        <td>9747.893</td>
        <td>546.000</td>
    </tr>
    <tr>
        <td>1539</td>
        <td><a href=players.php?pid=2128&edition=5>FalcoTM.</a></td>
        <td>2</td>
        <td>9747.907</td>
        <td>546.500</td>
    </tr>
    <tr>
        <td>1540</td>
        <td><a href=players.php?pid=36027&edition=5>Jay.db</a></td>
        <td>2</td>
        <td>9747.907</td>
        <td>546.500</td>
    </tr>
    <tr>
        <td>1541</td>
        <td><a href=players.php?pid=62330&edition=5>phoe30</a></td>
        <td>2</td>
        <td>9747.947</td>
        <td>548.000</td>
    </tr>
    <tr>
        <td>1542</td>
        <td><a href=players.php?pid=48587&edition=5>angel6059</a></td>
        <td>2</td>
        <td>9747.973</td>
        <td>549.000</td>
    </tr>
    <tr>
        <td>1543</td>
        <td><a href=players.php?pid=39209&edition=5>jeff_hossmen</a></td>
        <td>2</td>
        <td>9748.133</td>
        <td>555.000</td>
    </tr>
    <tr>
        <td>1544</td>
        <td><a href=players.php?pid=37482&edition=5>Joker</a></td>
        <td>2</td>
        <td>9748.133</td>
        <td>555.000</td>
    </tr>
    <tr>
        <td>1545</td>
        <td><a href=players.php?pid=71113&edition=5>RS_Axi0s</a></td>
        <td>2</td>
        <td>9748.227</td>
        <td>558.500</td>
    </tr>
    <tr>
        <td>1546</td>
        <td><a href=players.php?pid=52890&edition=5>mniiip</a></td>
        <td>2</td>
        <td>9748.253</td>
        <td>559.500</td>
    </tr>
    <tr>
        <td>1547</td>
        <td><a href=players.php?pid=67181&edition=5>DarQon.</a></td>
        <td>2</td>
        <td>9748.280</td>
        <td>560.500</td>
    </tr>
    <tr>
        <td>1548</td>
        <td><a href=players.php?pid=23389&edition=5>Nalax_tm</a></td>
        <td>2</td>
        <td>9748.400</td>
        <td>565.000</td>
    </tr>
    <tr>
        <td>1549</td>
        <td><a href=players.php?pid=42723&edition=5>not-IBratan</a></td>
        <td>2</td>
        <td>9748.867</td>
        <td>582.500</td>
    </tr>
    <tr>
        <td>1550</td>
        <td><a href=players.php?pid=70371&edition=5>scright</a></td>
        <td>2</td>
        <td>9748.893</td>
        <td>583.500</td>
    </tr>
    <tr>
        <td>1551</td>
        <td><a href=players.php?pid=45003&edition=5>Zapix_</a></td>
        <td>2</td>
        <td>9748.920</td>
        <td>584.500</td>
    </tr>
    <tr>
        <td>1552</td>
        <td><a href=players.php?pid=47017&edition=5>Ghost4ce</a></td>
        <td>2</td>
        <td>9748.947</td>
        <td>585.500</td>
    </tr>
    <tr>
        <td>1553</td>
        <td><a href=players.php?pid=34538&edition=5>Trifouilli06</a></td>
        <td>2</td>
        <td>9748.987</td>
        <td>587.000</td>
    </tr>
    <tr>
        <td>1554</td>
        <td><a href=players.php?pid=33395&edition=5>ardaftw</a></td>
        <td>2</td>
        <td>9749.013</td>
        <td>588.000</td>
    </tr>
    <tr>
        <td>1555</td>
        <td><a href=players.php?pid=9946&edition=5>illuminPhoenix</a></td>
        <td>2</td>
        <td>9749.107</td>
        <td>591.500</td>
    </tr>
    <tr>
        <td>1556</td>
        <td><a href=players.php?pid=9482&edition=5><span style='color:#ff33ff;'>u</span><span
                    style='color:#ff5588;'>в</span><span style='color:#ff6600;'>m</span><span
                    style='color:#ff6600;'>&reg;</span><span style='color:#ff0033;'>&sup3;</span></a></td>
        <td>2</td>
        <td>9749.160</td>
        <td>593.500</td>
    </tr>
    <tr>
        <td>1557</td>
        <td><a href=players.php?pid=12&edition=5>:kem1W:</a></td>
        <td>2</td>
        <td>9749.173</td>
        <td>594.000</td>
    </tr>
    <tr>
        <td>1558</td>
        <td><a href=players.php?pid=16082&edition=5>Jonesmen_10</a></td>
        <td>2</td>
        <td>9749.200</td>
        <td>595.000</td>
    </tr>
    <tr>
        <td>1559</td>
        <td><a href=players.php?pid=53678&edition=5>Axlov</a></td>
        <td>2</td>
        <td>9749.267</td>
        <td>597.500</td>
    </tr>
    <tr>
        <td>1560</td>
        <td><a href=players.php?pid=30853&edition=5>TTK_Dreamer</a></td>
        <td>2</td>
        <td>9749.333</td>
        <td>600.000</td>
    </tr>
    <tr>
        <td>1561</td>
        <td><a href=players.php?pid=35426&edition=5>jackdude01</a></td>
        <td>2</td>
        <td>9749.360</td>
        <td>601.000</td>
    </tr>
    <tr>
        <td>1562</td>
        <td><a href=players.php?pid=31602&edition=5><span style='color:#ffcccc;font-weight:bold;'>prog</span></a></td>
        <td>2</td>
        <td>9749.373</td>
        <td>601.500</td>
    </tr>
    <tr>
        <td>1563</td>
        <td><a href=players.php?pid=70383&edition=5>Rouliiane</a></td>
        <td>2</td>
        <td>9749.373</td>
        <td>601.500</td>
    </tr>
    <tr>
        <td>1564</td>
        <td><a href=players.php?pid=37656&edition=5><span style='color:#33ff99;'>V</span><span
                    style='color:#44ffaa;'>a</span><span style='color:#55ffaa;'>l</span><span
                    style='color:#77ffbb;'>i</span><span style='color:#88ffbb;'>n</span><span
                    style='color:#99ffcc;'>t</span><span style='color:#aaffdd;'>h</span><span
                    style='color:#bbffdd;'>e</span><span style='color:#ddffee;'>s</span><span
                    style='color:#eeffee;'>k</span><span style='color:#ffffff;'>y</span></a></td>
        <td>2</td>
        <td>9749.547</td>
        <td>608.000</td>
    </tr>
    <tr>
        <td>1565</td>
        <td><a href=players.php?pid=53368&edition=5>dusk969</a></td>
        <td>2</td>
        <td>9749.560</td>
        <td>608.500</td>
    </tr>
    <tr>
        <td>1566</td>
        <td><a href=players.php?pid=71061&edition=5>RipePlastic</a></td>
        <td>2</td>
        <td>9749.680</td>
        <td>613.000</td>
    </tr>
    <tr>
        <td>1567</td>
        <td><a href=players.php?pid=58932&edition=5>KasGaspar</a></td>
        <td>2</td>
        <td>9749.720</td>
        <td>614.500</td>
    </tr>
    <tr>
        <td>1568</td>
        <td><a href=players.php?pid=32146&edition=5>BadScam</a></td>
        <td>2</td>
        <td>9749.853</td>
        <td>619.500</td>
    </tr>
    <tr>
        <td>1569</td>
        <td><a href=players.php?pid=37194&edition=5><span style='color:#ff0000;'>B</span><span
                    style='color:#dd3333;'>u</span><span style='color:#aa5555;'>c</span><span
                    style='color:#888888;'>k</span><span style='color:#55aaaa;'>l</span><span
                    style='color:#33dddd;'>e</span><span style='color:#00ffff;'>y</span><span
                    style='color:#00ffff;'>s</span><span style='color:#33ffcc;'>P</span><span
                    style='color:#66ff99;'>a</span><span style='color:#99ff66;'>n</span><span
                    style='color:#ccff33;'>t</span><span style='color:#ffff00;'>s</span></a></td>
        <td>2</td>
        <td>9749.853</td>
        <td>619.500</td>
    </tr>
    <tr>
        <td>1570</td>
        <td><a href=players.php?pid=39372&edition=5>Anypsotis</a></td>
        <td>2</td>
        <td>9750.173</td>
        <td>631.500</td>
    </tr>
    <tr>
        <td>1571</td>
        <td><a href=players.php?pid=68016&edition=5>Kokir10</a></td>
        <td>2</td>
        <td>9750.213</td>
        <td>633.000</td>
    </tr>
    <tr>
        <td>1572</td>
        <td><a href=players.php?pid=68251&edition=5>EjdamCZ:prayge:</a></td>
        <td>2</td>
        <td>9750.213</td>
        <td>633.000</td>
    </tr>
    <tr>
        <td>1573</td>
        <td><a href=players.php?pid=51829&edition=5>Baolini</a></td>
        <td>2</td>
        <td>9750.293</td>
        <td>636.000</td>
    </tr>
    <tr>
        <td>1574</td>
        <td><a href=players.php?pid=12424&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;xXCARRELAGEXx</span></a></td>
        <td>2</td>
        <td>9750.307</td>
        <td>636.500</td>
    </tr>
    <tr>
        <td>1575</td>
        <td><a href=players.php?pid=67565&edition=5><span style='color:#00ccff;'>A</span><span
                    style='color:#55ccaa;'>b</span><span style='color:#aacc55;'>u</span><span
                    style='color:#ffcc00;'>M</span><span style='color:#ffcc00;'>e</span><span
                    style='color:#88cc00;'>c</span><span style='color:#00cc00;'>h</span></a></td>
        <td>2</td>
        <td>9750.387</td>
        <td>639.500</td>
    </tr>
    <tr>
        <td>1576</td>
        <td><a href=players.php?pid=9343&edition=5>SweetIto</a></td>
        <td>2</td>
        <td>9750.413</td>
        <td>640.500</td>
    </tr>
    <tr>
        <td>1577</td>
        <td><a href=players.php?pid=39382&edition=5>Auudacity</a></td>
        <td>2</td>
        <td>9750.440</td>
        <td>641.500</td>
    </tr>
    <tr>
        <td>1578</td>
        <td><a href=players.php?pid=45881&edition=5>H4buen</a></td>
        <td>2</td>
        <td>9750.560</td>
        <td>646.000</td>
    </tr>
    <tr>
        <td>1579</td>
        <td><a href=players.php?pid=67177&edition=5>Super_VooDoo</a></td>
        <td>2</td>
        <td>9750.600</td>
        <td>647.500</td>
    </tr>
    <tr>
        <td>1580</td>
        <td><a href=players.php?pid=8806&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Jesusededbits</span></a></td>
        <td>2</td>
        <td>9750.667</td>
        <td>650.000</td>
    </tr>
    <tr>
        <td>1581</td>
        <td><a href=players.php?pid=11219&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;</span><span style='color:#006666;'>mr.</span><span
                    style='color:#ffffff;'>iosa</span></a></td>
        <td>2</td>
        <td>9751.013</td>
        <td>663.000</td>
    </tr>
    <tr>
        <td>1582</td>
        <td><a href=players.php?pid=70044&edition=5>touro-_-</a></td>
        <td>2</td>
        <td>9751.107</td>
        <td>666.500</td>
    </tr>
    <tr>
        <td>1583</td>
        <td><a href=players.php?pid=17160&edition=5>fred&nbsp;:owo:&nbsp;lf</a></td>
        <td>2</td>
        <td>9751.173</td>
        <td>669.000</td>
    </tr>
    <tr>
        <td>1584</td>
        <td><a href=players.php?pid=51720&edition=5>marsal06</a></td>
        <td>2</td>
        <td>9751.187</td>
        <td>669.500</td>
    </tr>
    <tr>
        <td>1585</td>
        <td><a href=players.php?pid=9621&edition=5>the_moc</a></td>
        <td>2</td>
        <td>9751.267</td>
        <td>672.500</td>
    </tr>
    <tr>
        <td>1586</td>
        <td><a href=players.php?pid=30842&edition=5>NKJ.</a></td>
        <td>2</td>
        <td>9751.293</td>
        <td>673.500</td>
    </tr>
    <tr>
        <td>1587</td>
        <td><a href=players.php?pid=51807&edition=5><span style='color:#007700;'>PS204</span></a></td>
        <td>2</td>
        <td>9751.320</td>
        <td>674.500</td>
    </tr>
    <tr>
        <td>1588</td>
        <td><a href=players.php?pid=71708&edition=5>Sillossoss</a></td>
        <td>2</td>
        <td>9751.520</td>
        <td>682.000</td>
    </tr>
    <tr>
        <td>1589</td>
        <td><a href=players.php?pid=62774&edition=5>TommyG012</a></td>
        <td>2</td>
        <td>9751.547</td>
        <td>683.000</td>
    </tr>
    <tr>
        <td>1590</td>
        <td><a href=players.php?pid=49270&edition=5>onigod-</a></td>
        <td>2</td>
        <td>9751.547</td>
        <td>683.000</td>
    </tr>
    <tr>
        <td>1591</td>
        <td><a href=players.php?pid=63765&edition=5>snake.legs</a></td>
        <td>2</td>
        <td>9751.560</td>
        <td>683.500</td>
    </tr>
    <tr>
        <td>1592</td>
        <td><a href=players.php?pid=31815&edition=5><span style='color:#ff7700;'>C</span>0<span
                    style='color:#ff7700;'>T&nbsp;</span><span style='color:#ffffff;'>|&nbsp;Ydien</span></a></td>
        <td>2</td>
        <td>9751.627</td>
        <td>686.000</td>
    </tr>
    <tr>
        <td>1593</td>
        <td><a href=players.php?pid=6709&edition=5>urasmellyduck</a></td>
        <td>2</td>
        <td>9751.773</td>
        <td>691.500</td>
    </tr>
    <tr>
        <td>1594</td>
        <td><a href=players.php?pid=67767&edition=5>oen-_-</a></td>
        <td>2</td>
        <td>9751.800</td>
        <td>692.500</td>
    </tr>
    <tr>
        <td>1595</td>
        <td><a href=players.php?pid=67403&edition=5>Equarmar</a></td>
        <td>2</td>
        <td>9751.813</td>
        <td>693.000</td>
    </tr>
    <tr>
        <td>1596</td>
        <td><a href=players.php?pid=67518&edition=5>dijle1</a></td>
        <td>2</td>
        <td>9751.867</td>
        <td>695.000</td>
    </tr>
    <tr>
        <td>1597</td>
        <td><a href=players.php?pid=70936&edition=5>AAAABattery</a></td>
        <td>2</td>
        <td>9751.867</td>
        <td>695.000</td>
    </tr>
    <tr>
        <td>1598</td>
        <td><a href=players.php?pid=67376&edition=5>Myth0cal.TM</a></td>
        <td>2</td>
        <td>9751.907</td>
        <td>696.500</td>
    </tr>
    <tr>
        <td>1599</td>
        <td><a href=players.php?pid=69807&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Raycki</span></a></td>
        <td>2</td>
        <td>9751.960</td>
        <td>698.500</td>
    </tr>
    <tr>
        <td>1600</td>
        <td><a href=players.php?pid=26111&edition=5>Hyzer.John</a></td>
        <td>2</td>
        <td>9751.987</td>
        <td>699.500</td>
    </tr>
    <tr>
        <td>1601</td>
        <td><a href=players.php?pid=1361&edition=5>PurpleLyle</a></td>
        <td>2</td>
        <td>9751.987</td>
        <td>699.500</td>
    </tr>
    <tr>
        <td>1602</td>
        <td><a href=players.php?pid=68798&edition=5>L3xTr0n88</a></td>
        <td>2</td>
        <td>9752.080</td>
        <td>703.000</td>
    </tr>
    <tr>
        <td>1603</td>
        <td><a href=players.php?pid=29609&edition=5><span style='color:#ff00cc;'>&kappa;</span><span
                    style='color:#ff00aa;'>ǘ</span><span style='color:#ff0088;'>г</span><span
                    style='color:#ff0066;'>义</span></a></td>
        <td>2</td>
        <td>9752.213</td>
        <td>708.000</td>
    </tr>
    <tr>
        <td>1604</td>
        <td><a href=players.php?pid=53735&edition=5>SiYess</a></td>
        <td>2</td>
        <td>9752.293</td>
        <td>711.000</td>
    </tr>
    <tr>
        <td>1605</td>
        <td><a href=players.php?pid=52750&edition=5>'Lex</a></td>
        <td>2</td>
        <td>9752.387</td>
        <td>714.500</td>
    </tr>
    <tr>
        <td>1606</td>
        <td><a href=players.php?pid=69499&edition=5>DnB_EMBER</a></td>
        <td>2</td>
        <td>9752.493</td>
        <td>718.500</td>
    </tr>
    <tr>
        <td>1607</td>
        <td><a href=players.php?pid=57727&edition=5><span style='color:#9900ff;'>T</span><span
                    style='color:#8811ff;'>r</span><span style='color:#7722ff;'>e</span><span
                    style='color:#6633ff;'>n</span><span style='color:#6633ff;'>t</span><span
                    style='color:#3399ff;'>e</span><span style='color:#00ffff;'>R</span></a></td>
        <td>2</td>
        <td>9752.600</td>
        <td>722.500</td>
    </tr>
    <tr>
        <td>1608</td>
        <td><a href=players.php?pid=54493&edition=5>ItsFobie</a></td>
        <td>2</td>
        <td>9752.600</td>
        <td>722.500</td>
    </tr>
    <tr>
        <td>1609</td>
        <td><a href=players.php?pid=146&edition=5>Prime_S</a></td>
        <td>2</td>
        <td>9752.667</td>
        <td>725.000</td>
    </tr>
    <tr>
        <td>1610</td>
        <td><a href=players.php?pid=54178&edition=5>Gurkpasta</a></td>
        <td>2</td>
        <td>9752.680</td>
        <td>725.500</td>
    </tr>
    <tr>
        <td>1611</td>
        <td><a href=players.php?pid=57634&edition=5>ElkinAround</a></td>
        <td>2</td>
        <td>9752.693</td>
        <td>726.000</td>
    </tr>
    <tr>
        <td>1612</td>
        <td><a href=players.php?pid=44765&edition=5>Linus24.</a></td>
        <td>2</td>
        <td>9752.720</td>
        <td>727.000</td>
    </tr>
    <tr>
        <td>1613</td>
        <td><a href=players.php?pid=68619&edition=5>Notchyo_Cheese</a></td>
        <td>2</td>
        <td>9752.893</td>
        <td>733.500</td>
    </tr>
    <tr>
        <td>1614</td>
        <td><a href=players.php?pid=48103&edition=5>pisingr22</a></td>
        <td>2</td>
        <td>9753.000</td>
        <td>737.500</td>
    </tr>
    <tr>
        <td>1615</td>
        <td><a href=players.php?pid=81&edition=5>WiiL0x</a></td>
        <td>2</td>
        <td>9753.120</td>
        <td>742.000</td>
    </tr>
    <tr>
        <td>1616</td>
        <td><a href=players.php?pid=69789&edition=5><span style='color:#9933ff;'>j</span><span
                    style='color:#aa44cc;'>a</span><span style='color:#bb5599;'>d</span><span
                    style='color:#bb5566;'>e</span><span style='color:#cc6633;'>e</span><span
                    style='color:#cc6633;'>b</span><span style='color:#dd9922;'>i</span><span
                    style='color:#eecc11;'>r</span><span style='color:#ffff00;'>b</span></a></td>
        <td>2</td>
        <td>9753.120</td>
        <td>742.000</td>
    </tr>
    <tr>
        <td>1617</td>
        <td><a href=players.php?pid=46076&edition=5>PaolKuak</a></td>
        <td>2</td>
        <td>9753.187</td>
        <td>744.500</td>
    </tr>
    <tr>
        <td>1618</td>
        <td><a href=players.php?pid=68845&edition=5><span
                    style='color:#ff0000;font-style:italic;font-weight:bold;'>The</span><span
                    style='color:#000000;font-style:italic;font-weight:bold;'>Nob</span><span
                    style='color:#ff0000;font-style:italic;font-weight:bold;'>sal</span></a></td>
        <td>2</td>
        <td>9753.227</td>
        <td>746.000</td>
    </tr>
    <tr>
        <td>1619</td>
        <td><a href=players.php?pid=43730&edition=5>Redset__</a></td>
        <td>2</td>
        <td>9753.253</td>
        <td>747.000</td>
    </tr>
    <tr>
        <td>1620</td>
        <td><a href=players.php?pid=52559&edition=5>noldyy_</a></td>
        <td>2</td>
        <td>9753.267</td>
        <td>747.500</td>
    </tr>
    <tr>
        <td>1621</td>
        <td><a href=players.php?pid=32301&edition=5>Salin17</a></td>
        <td>2</td>
        <td>9753.280</td>
        <td>748.000</td>
    </tr>
    <tr>
        <td>1622</td>
        <td><a href=players.php?pid=25466&edition=5><span style='color:#ff0000;'>J</span><span
                    style='color:#ff4444;'>e</span><span style='color:#ff8888;'>s</span><span
                    style='color:#ffbbbb;'>s</span><span style='color:#ffffff;'>e</span><span
                    style='color:#ffffff;'>W</span>0<span style='color:#5555ff;'>7</span>0</a></td>
        <td>2</td>
        <td>9753.333</td>
        <td>750.000</td>
    </tr>
    <tr>
        <td>1623</td>
        <td><a href=players.php?pid=63729&edition=5>Motam06</a></td>
        <td>2</td>
        <td>9753.347</td>
        <td>750.500</td>
    </tr>
    <tr>
        <td>1624</td>
        <td><a href=players.php?pid=58654&edition=5>DoobiePuffer</a></td>
        <td>2</td>
        <td>9753.360</td>
        <td>751.000</td>
    </tr>
    <tr>
        <td>1625</td>
        <td><a href=players.php?pid=22447&edition=5>Bastoune.TM</a></td>
        <td>2</td>
        <td>9753.480</td>
        <td>755.500</td>
    </tr>
    <tr>
        <td>1626</td>
        <td><a href=players.php?pid=18035&edition=5>StefanGose91</a></td>
        <td>2</td>
        <td>9753.547</td>
        <td>758.000</td>
    </tr>
    <tr>
        <td>1627</td>
        <td><a href=players.php?pid=47803&edition=5><span style='color:#660066;'>W</span><span
                    style='color:#006600;'>indz</span><span style='color:#660066;'>y</span></a></td>
        <td>2</td>
        <td>9753.560</td>
        <td>758.500</td>
    </tr>
    <tr>
        <td>1628</td>
        <td><a href=players.php?pid=31662&edition=5>Filpsor</a></td>
        <td>2</td>
        <td>9753.693</td>
        <td>763.500</td>
    </tr>
    <tr>
        <td>1629</td>
        <td><a href=players.php?pid=3238&edition=5><span style='color:#bb0099;'>D</span><span
                    style='color:#cc44bb;'>j</span><span style='color:#dd99cc;'>a</span><span
                    style='color:#eeddee;'>n</span><span style='color:#eeddee;'>g</span><span
                    style='color:#eebbdd;'>V</span><span style='color:#ddaadd;'>o</span><span
                    style='color:#dd88cc;'>w</span><span style='color:#dd66cc;'>o</span></a></td>
        <td>2</td>
        <td>9753.720</td>
        <td>764.500</td>
    </tr>
    <tr>
        <td>1630</td>
        <td><a href=players.php?pid=6441&edition=5>DominoMiz</a></td>
        <td>2</td>
        <td>9753.720</td>
        <td>764.500</td>
    </tr>
    <tr>
        <td>1631</td>
        <td><a href=players.php?pid=67260&edition=5>Hamza_cuber55</a></td>
        <td>2</td>
        <td>9753.800</td>
        <td>767.500</td>
    </tr>
    <tr>
        <td>1632</td>
        <td><a href=players.php?pid=27911&edition=5><span style='color:#6699ff;'>blauball</span></a></td>
        <td>2</td>
        <td>9753.893</td>
        <td>771.000</td>
    </tr>
    <tr>
        <td>1633</td>
        <td><a href=players.php?pid=66360&edition=5><span style='color:#ffbb00;'>B</span><span
                    style='color:#000000;'>H</span><span style='color:#ffbb00;'>I</span><span
                    style='color:#000000;'>V</span><span style='color:#ffbb00;'>e</span></a></td>
        <td>2</td>
        <td>9753.907</td>
        <td>771.500</td>
    </tr>
    <tr>
        <td>1634</td>
        <td><a href=players.php?pid=46500&edition=5>Cal._.</a></td>
        <td>2</td>
        <td>9754.147</td>
        <td>780.500</td>
    </tr>
    <tr>
        <td>1635</td>
        <td><a href=players.php?pid=66579&edition=5>loloverrrr</a></td>
        <td>2</td>
        <td>9754.480</td>
        <td>793.000</td>
    </tr>
    <tr>
        <td>1636</td>
        <td><a href=players.php?pid=53666&edition=5>pixelshaw</a></td>
        <td>2</td>
        <td>9754.613</td>
        <td>798.000</td>
    </tr>
    <tr>
        <td>1637</td>
        <td><a href=players.php?pid=53840&edition=5>karagara</a></td>
        <td>2</td>
        <td>9754.613</td>
        <td>798.000</td>
    </tr>
    <tr>
        <td>1638</td>
        <td><a href=players.php?pid=10280&edition=5>NinjaXMII</a></td>
        <td>2</td>
        <td>9754.707</td>
        <td>801.500</td>
    </tr>
    <tr>
        <td>1639</td>
        <td><a href=players.php?pid=67890&edition=5>RichHard98</a></td>
        <td>2</td>
        <td>9754.827</td>
        <td>806.000</td>
    </tr>
    <tr>
        <td>1640</td>
        <td><a href=players.php?pid=69041&edition=5>Shrike841</a></td>
        <td>2</td>
        <td>9754.840</td>
        <td>806.500</td>
    </tr>
    <tr>
        <td>1641</td>
        <td><a href=players.php?pid=66986&edition=5>Hudsonjime1</a></td>
        <td>2</td>
        <td>9754.867</td>
        <td>807.500</td>
    </tr>
    <tr>
        <td>1642</td>
        <td><a href=players.php?pid=49888&edition=5>MythicalPingu</a></td>
        <td>2</td>
        <td>9755.013</td>
        <td>813.000</td>
    </tr>
    <tr>
        <td>1643</td>
        <td><a href=players.php?pid=52477&edition=5>JDiamond972</a></td>
        <td>2</td>
        <td>9755.027</td>
        <td>813.500</td>
    </tr>
    <tr>
        <td>1644</td>
        <td><a href=players.php?pid=66895&edition=5>ooBuu</a></td>
        <td>2</td>
        <td>9755.107</td>
        <td>816.500</td>
    </tr>
    <tr>
        <td>1645</td>
        <td><a href=players.php?pid=62175&edition=5>Maxord3000</a></td>
        <td>2</td>
        <td>9755.133</td>
        <td>817.500</td>
    </tr>
    <tr>
        <td>1646</td>
        <td><a href=players.php?pid=69639&edition=5>Jonas4n</a></td>
        <td>2</td>
        <td>9755.173</td>
        <td>819.000</td>
    </tr>
    <tr>
        <td>1647</td>
        <td><a href=players.php?pid=34489&edition=5><span style='color:#9966ff;font-weight:bold;'>Te</span><span
                    style='color:#8866ff;font-weight:bold;'>K</span><span
                    style='color:#8866ee;font-weight:bold;'>a</span><span
                    style='color:#7766ee;font-weight:bold;'>yy</span></a></td>
        <td>2</td>
        <td>9755.227</td>
        <td>821.000</td>
    </tr>
    <tr>
        <td>1648</td>
        <td><a href=players.php?pid=69313&edition=5>JoaoZiiN2006</a></td>
        <td>2</td>
        <td>9755.240</td>
        <td>821.500</td>
    </tr>
    <tr>
        <td>1649</td>
        <td><a href=players.php?pid=66733&edition=5>olofpalme1927</a></td>
        <td>2</td>
        <td>9755.240</td>
        <td>821.500</td>
    </tr>
    <tr>
        <td>1650</td>
        <td><a href=players.php?pid=10414&edition=5>kreth-</a></td>
        <td>2</td>
        <td>9755.267</td>
        <td>822.500</td>
    </tr>
    <tr>
        <td>1651</td>
        <td><a href=players.php?pid=70527&edition=5>jaevs</a></td>
        <td>2</td>
        <td>9755.467</td>
        <td>830.000</td>
    </tr>
    <tr>
        <td>1652</td>
        <td><a href=players.php?pid=27188&edition=5>zapgun7</a></td>
        <td>2</td>
        <td>9755.493</td>
        <td>831.000</td>
    </tr>
    <tr>
        <td>1653</td>
        <td><a href=players.php?pid=8351&edition=5>ZuStoned420</a></td>
        <td>2</td>
        <td>9755.507</td>
        <td>831.500</td>
    </tr>
    <tr>
        <td>1654</td>
        <td><a href=players.php?pid=70381&edition=5>GameMoveCZ</a></td>
        <td>2</td>
        <td>9755.520</td>
        <td>832.000</td>
    </tr>
    <tr>
        <td>1655</td>
        <td><a href=players.php?pid=67359&edition=5>War_Boredom</a></td>
        <td>2</td>
        <td>9755.560</td>
        <td>833.500</td>
    </tr>
    <tr>
        <td>1656</td>
        <td><a href=players.php?pid=32068&edition=5><span style='color:#00aabb;font-weight:bold;'>Ƞ</span><span
                    style='color:#000000;font-weight:bold;'>4</span><span
                    style='color:#00aabb;font-weight:bold;'>Ɍ</span><span
                    style='color:#000000;font-weight:bold;'>Ȼ</span><span
                    style='color:#00aabb;font-weight:bold;'>1</span></a></td>
        <td>2</td>
        <td>9755.573</td>
        <td>834.000</td>
    </tr>
    <tr>
        <td>1657</td>
        <td><a href=players.php?pid=64193&edition=5>dankovil</a></td>
        <td>2</td>
        <td>9755.613</td>
        <td>835.500</td>
    </tr>
    <tr>
        <td>1658</td>
        <td><a href=players.php?pid=32136&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;WilOvent</span></a></td>
        <td>2</td>
        <td>9755.613</td>
        <td>835.500</td>
    </tr>
    <tr>
        <td>1659</td>
        <td><a href=players.php?pid=12646&edition=5>That----Guy74</a></td>
        <td>2</td>
        <td>9755.640</td>
        <td>836.500</td>
    </tr>
    <tr>
        <td>1660</td>
        <td><a href=players.php?pid=72074&edition=5>Velonote</a></td>
        <td>2</td>
        <td>9755.680</td>
        <td>838.000</td>
    </tr>
    <tr>
        <td>1661</td>
        <td><a href=players.php?pid=65918&edition=5>Pistimistike</a></td>
        <td>2</td>
        <td>9755.760</td>
        <td>841.000</td>
    </tr>
    <tr>
        <td>1662</td>
        <td><a href=players.php?pid=66460&edition=5>Pr0_T0_TyPE</a></td>
        <td>2</td>
        <td>9755.813</td>
        <td>843.000</td>
    </tr>
    <tr>
        <td>1663</td>
        <td><a href=players.php?pid=65030&edition=5>AndrobalTM</a></td>
        <td>2</td>
        <td>9755.920</td>
        <td>847.000</td>
    </tr>
    <tr>
        <td>1664</td>
        <td><a href=players.php?pid=63953&edition=5>qwerty12944</a></td>
        <td>2</td>
        <td>9755.920</td>
        <td>847.000</td>
    </tr>
    <tr>
        <td>1665</td>
        <td><a href=players.php?pid=68341&edition=5>Stabilizations1</a></td>
        <td>2</td>
        <td>9756.027</td>
        <td>851.000</td>
    </tr>
    <tr>
        <td>1666</td>
        <td><a href=players.php?pid=66143&edition=5>Darkeyyyyy</a></td>
        <td>2</td>
        <td>9756.107</td>
        <td>854.000</td>
    </tr>
    <tr>
        <td>1667</td>
        <td><a href=players.php?pid=64784&edition=5>Jaypes_TM</a></td>
        <td>2</td>
        <td>9756.160</td>
        <td>856.000</td>
    </tr>
    <tr>
        <td>1668</td>
        <td><a href=players.php?pid=54976&edition=5>GK_NK98</a></td>
        <td>2</td>
        <td>9756.173</td>
        <td>856.500</td>
    </tr>
    <tr>
        <td>1669</td>
        <td><a href=players.php?pid=67057&edition=5>atomicans</a></td>
        <td>2</td>
        <td>9756.213</td>
        <td>858.000</td>
    </tr>
    <tr>
        <td>1670</td>
        <td><a href=players.php?pid=35766&edition=5>hlawa7l8oom.sax</a></td>
        <td>2</td>
        <td>9756.280</td>
        <td>860.500</td>
    </tr>
    <tr>
        <td>1671</td>
        <td><a href=players.php?pid=7505&edition=5>BIGJLF7</a></td>
        <td>2</td>
        <td>9756.280</td>
        <td>860.500</td>
    </tr>
    <tr>
        <td>1672</td>
        <td><a href=players.php?pid=67349&edition=5>LAUZ_</a></td>
        <td>2</td>
        <td>9756.507</td>
        <td>869.000</td>
    </tr>
    <tr>
        <td>1673</td>
        <td><a href=players.php?pid=53611&edition=5>MikaelSkomaker</a></td>
        <td>2</td>
        <td>9756.533</td>
        <td>870.000</td>
    </tr>
    <tr>
        <td>1674</td>
        <td><a href=players.php?pid=57864&edition=5>FreakZz2801</a></td>
        <td>2</td>
        <td>9756.627</td>
        <td>873.500</td>
    </tr>
    <tr>
        <td>1675</td>
        <td><a href=players.php?pid=9015&edition=5>CheriCheriSir</a></td>
        <td>2</td>
        <td>9756.640</td>
        <td>874.000</td>
    </tr>
    <tr>
        <td>1676</td>
        <td><a href=players.php?pid=66403&edition=5><span style='color:#0066ff;font-style:italic;'>K</span><span
                    style='color:#2277dd;font-style:italic;'>a</span><span
                    style='color:#4499bb;font-style:italic;'>a</span><span
                    style='color:#66aa99;font-style:italic;'>s</span><span
                    style='color:#99bb66;font-style:italic;'>l</span><span
                    style='color:#bbcc44;font-style:italic;'>o</span><span
                    style='color:#ddee22;font-style:italic;'>l</span><span
                    style='color:#ffff00;font-style:italic;'>1</span></a></td>
        <td>2</td>
        <td>9756.880</td>
        <td>883.000</td>
    </tr>
    <tr>
        <td>1677</td>
        <td><a href=players.php?pid=2894&edition=5><span style='color:#ff00ff;'>Ken</span><span
                    style='color:#ff00ff;'>n</span><span style='color:#ee00ff;'>o</span><span
                    style='color:#cc00ff;'>x</span></a></td>
        <td>2</td>
        <td>9756.933</td>
        <td>885.000</td>
    </tr>
    <tr>
        <td>1678</td>
        <td><a href=players.php?pid=56162&edition=5>s1deex</a></td>
        <td>2</td>
        <td>9757.093</td>
        <td>891.000</td>
    </tr>
    <tr>
        <td>1679</td>
        <td><a href=players.php?pid=37468&edition=5>covertcody</a></td>
        <td>2</td>
        <td>9757.187</td>
        <td>894.500</td>
    </tr>
    <tr>
        <td>1680</td>
        <td><a href=players.php?pid=64096&edition=5>Menjoew</a></td>
        <td>2</td>
        <td>9757.213</td>
        <td>895.500</td>
    </tr>
    <tr>
        <td>1681</td>
        <td><a href=players.php?pid=67428&edition=5>Solania_</a></td>
        <td>2</td>
        <td>9757.227</td>
        <td>896.000</td>
    </tr>
    <tr>
        <td>1682</td>
        <td><a href=players.php?pid=51084&edition=5>Flooww_TM</a></td>
        <td>2</td>
        <td>9757.227</td>
        <td>896.000</td>
    </tr>
    <tr>
        <td>1683</td>
        <td><a href=players.php?pid=43099&edition=5>better0fdying</a></td>
        <td>2</td>
        <td>9757.240</td>
        <td>896.500</td>
    </tr>
    <tr>
        <td>1684</td>
        <td><a href=players.php?pid=60568&edition=5>PPGA-Bread</a></td>
        <td>2</td>
        <td>9757.267</td>
        <td>897.500</td>
    </tr>
    <tr>
        <td>1685</td>
        <td><a href=players.php?pid=66005&edition=5>mac-clane</a></td>
        <td>2</td>
        <td>9757.293</td>
        <td>898.500</td>
    </tr>
    <tr>
        <td>1686</td>
        <td><a href=players.php?pid=69642&edition=5>Daft_Deity</a></td>
        <td>2</td>
        <td>9757.653</td>
        <td>912.000</td>
    </tr>
    <tr>
        <td>1687</td>
        <td><a href=players.php?pid=66849&edition=5><span style='color:#0033cc;'>B</span><span
                    style='color:#3355aa;'>a</span><span style='color:#557788;'>s</span><span
                    style='color:#889966;'>h</span><span style='color:#aabb44;'>m</span><span
                    style='color:#dddd22;'>e</span><span style='color:#ffff00;'>g</span></a></td>
        <td>2</td>
        <td>9757.933</td>
        <td>922.500</td>
    </tr>
    <tr>
        <td>1688</td>
        <td><a href=players.php?pid=66853&edition=5>Timmovic123.</a></td>
        <td>2</td>
        <td>9757.960</td>
        <td>923.500</td>
    </tr>
    <tr>
        <td>1689</td>
        <td><a href=players.php?pid=71215&edition=5>Mizzi_dk</a></td>
        <td>2</td>
        <td>9757.960</td>
        <td>923.500</td>
    </tr>
    <tr>
        <td>1690</td>
        <td><a href=players.php?pid=67624&edition=5>Naoz_</a></td>
        <td>2</td>
        <td>9758.027</td>
        <td>926.000</td>
    </tr>
    <tr>
        <td>1691</td>
        <td><a href=players.php?pid=39680&edition=5>FleriX_TM</a></td>
        <td>2</td>
        <td>9758.267</td>
        <td>935.000</td>
    </tr>
    <tr>
        <td>1692</td>
        <td><a href=players.php?pid=36877&edition=5>P1nski</a></td>
        <td>2</td>
        <td>9758.320</td>
        <td>937.000</td>
    </tr>
    <tr>
        <td>1693</td>
        <td><a href=players.php?pid=57277&edition=5>notJrd</a></td>
        <td>2</td>
        <td>9758.400</td>
        <td>940.000</td>
    </tr>
    <tr>
        <td>1694</td>
        <td><a href=players.php?pid=16624&edition=5>Xsnabb_</a></td>
        <td>2</td>
        <td>9758.453</td>
        <td>942.000</td>
    </tr>
    <tr>
        <td>1695</td>
        <td><a href=players.php?pid=65936&edition=5><span style='color:#ffffff;'>Ǥ</span><span
                    style='color:#eeeeee;'>ћ</span><span style='color:#cccccc;'>ѻ</span><span
                    style='color:#cccccc;'>Ϩ</span><span style='color:#000000;'>ϯ</span></a></td>
        <td>2</td>
        <td>9758.547</td>
        <td>945.500</td>
    </tr>
    <tr>
        <td>1696</td>
        <td><a href=players.php?pid=66915&edition=5>Ake60</a></td>
        <td>2</td>
        <td>9758.560</td>
        <td>946.000</td>
    </tr>
    <tr>
        <td>1697</td>
        <td><a href=players.php?pid=66209&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>Aku__</span></a></td>
        <td>2</td>
        <td>9758.573</td>
        <td>946.500</td>
    </tr>
    <tr>
        <td>1698</td>
        <td><a href=players.php?pid=69758&edition=5>kobeph21</a></td>
        <td>2</td>
        <td>9758.573</td>
        <td>946.500</td>
    </tr>
    <tr>
        <td>1699</td>
        <td><a href=players.php?pid=95&edition=5>Davidodie</a></td>
        <td>2</td>
        <td>9758.600</td>
        <td>947.500</td>
    </tr>
    <tr>
        <td>1700</td>
        <td><a href=players.php?pid=28550&edition=5>AttanoCRO</a></td>
        <td>2</td>
        <td>9758.667</td>
        <td>950.000</td>
    </tr>
    <tr>
        <td>1701</td>
        <td><a href=players.php?pid=56267&edition=5>lolionel</a></td>
        <td>2</td>
        <td>9758.800</td>
        <td>955.000</td>
    </tr>
    <tr>
        <td>1702</td>
        <td><a href=players.php?pid=48447&edition=5>Tomasus</a></td>
        <td>2</td>
        <td>9758.813</td>
        <td>955.500</td>
    </tr>
    <tr>
        <td>1703</td>
        <td><a href=players.php?pid=43101&edition=5><span style='color:#6633ff;'>b</span><span
                    style='color:#3355ee;'>i</span><span style='color:#0066cc;'>n</span><span
                    style='color:#0066cc;'>a</span><span style='color:#663366;'>r</span><span
                    style='color:#cc0000;'>y</span></a></td>
        <td>2</td>
        <td>9758.827</td>
        <td>956.000</td>
    </tr>
    <tr>
        <td>1704</td>
        <td><a href=players.php?pid=63741&edition=5>KebbiTM</a></td>
        <td>2</td>
        <td>9758.840</td>
        <td>956.500</td>
    </tr>
    <tr>
        <td>1705</td>
        <td><a href=players.php?pid=68001&edition=5>Toukee</a></td>
        <td>2</td>
        <td>9758.840</td>
        <td>956.500</td>
    </tr>
    <tr>
        <td>1706</td>
        <td><a href=players.php?pid=32201&edition=5><span style='color:#00cc33;'>B</span><span
                    style='color:#00cc66;'>e</span><span style='color:#00cc99;'>d</span><span
                    style='color:#00cc99;'>e</span><span style='color:#00ccbb;'>u</span><span
                    style='color:#00cccc;'>x</span></a></td>
        <td>2</td>
        <td>9758.853</td>
        <td>957.000</td>
    </tr>
    <tr>
        <td>1707</td>
        <td><a href=players.php?pid=69987&edition=5>foxfarme</a></td>
        <td>2</td>
        <td>9758.893</td>
        <td>958.500</td>
    </tr>
    <tr>
        <td>1708</td>
        <td><a href=players.php?pid=68636&edition=5>DrSpontanicus</a></td>
        <td>2</td>
        <td>9758.973</td>
        <td>961.500</td>
    </tr>
    <tr>
        <td>1709</td>
        <td><a href=players.php?pid=62751&edition=5>Pena1g</a></td>
        <td>2</td>
        <td>9759.053</td>
        <td>964.500</td>
    </tr>
    <tr>
        <td>1710</td>
        <td><a href=players.php?pid=23561&edition=5>hawk&nbsp;tuah</a></td>
        <td>2</td>
        <td>9759.093</td>
        <td>966.000</td>
    </tr>
    <tr>
        <td>1711</td>
        <td><a href=players.php?pid=32077&edition=5><span style='color:#0000ff;'>K</span><span
                    style='color:#ffffff;'>ola</span><span style='color:#0000ff;'>-</span><span
                    style='color:#ffffff;'>.</span><span style='color:#0000ff;'>-</span></a></td>
        <td>2</td>
        <td>9759.093</td>
        <td>966.000</td>
    </tr>
    <tr>
        <td>1712</td>
        <td><a href=players.php?pid=32466&edition=5>PINGYER</a></td>
        <td>2</td>
        <td>9759.107</td>
        <td>966.500</td>
    </tr>
    <tr>
        <td>1713</td>
        <td><a href=players.php?pid=6632&edition=5>Rasmusik</a></td>
        <td>2</td>
        <td>9759.120</td>
        <td>967.000</td>
    </tr>
    <tr>
        <td>1714</td>
        <td><a href=players.php?pid=40619&edition=5>IplayOnMyLaptop</a></td>
        <td>2</td>
        <td>9759.147</td>
        <td>968.000</td>
    </tr>
    <tr>
        <td>1715</td>
        <td><a href=players.php?pid=55582&edition=5>fgtpp</a></td>
        <td>2</td>
        <td>9759.187</td>
        <td>969.500</td>
    </tr>
    <tr>
        <td>1716</td>
        <td><a href=players.php?pid=13308&edition=5>Highwanted</a></td>
        <td>2</td>
        <td>9759.373</td>
        <td>976.500</td>
    </tr>
    <tr>
        <td>1717</td>
        <td><a href=players.php?pid=67557&edition=5>n00bdax</a></td>
        <td>2</td>
        <td>9759.520</td>
        <td>982.000</td>
    </tr>
    <tr>
        <td>1718</td>
        <td><a href=players.php?pid=9498&edition=5>xHuqert</a></td>
        <td>2</td>
        <td>9759.640</td>
        <td>986.500</td>
    </tr>
    <tr>
        <td>1719</td>
        <td><a href=players.php?pid=52140&edition=5>Graves.TM</a></td>
        <td>2</td>
        <td>9759.693</td>
        <td>988.500</td>
    </tr>
    <tr>
        <td>1720</td>
        <td><a href=players.php?pid=4134&edition=5>Matifex18</a></td>
        <td>2</td>
        <td>9759.707</td>
        <td>989.000</td>
    </tr>
    <tr>
        <td>1721</td>
        <td><a href=players.php?pid=1999&edition=5>Gold.TM</a></td>
        <td>2</td>
        <td>9759.827</td>
        <td>993.500</td>
    </tr>
    <tr>
        <td>1722</td>
        <td><a href=players.php?pid=54023&edition=5>Connal_</a></td>
        <td>2</td>
        <td>9759.840</td>
        <td>994.000</td>
    </tr>
    <tr>
        <td>1723</td>
        <td><a href=players.php?pid=69799&edition=5>KuzonRL</a></td>
        <td>2</td>
        <td>9760.147</td>
        <td>1005.500</td>
    </tr>
    <tr>
        <td>1724</td>
        <td><a href=players.php?pid=45287&edition=5>osteole</a></td>
        <td>2</td>
        <td>9760.427</td>
        <td>1016.000</td>
    </tr>
    <tr>
        <td>1725</td>
        <td><a href=players.php?pid=51547&edition=5>fherme</a></td>
        <td>2</td>
        <td>9760.747</td>
        <td>1028.000</td>
    </tr>
    <tr>
        <td>1726</td>
        <td><a href=players.php?pid=53351&edition=5>GlyperionGaming</a></td>
        <td>2</td>
        <td>9761.067</td>
        <td>1040.000</td>
    </tr>
    <tr>
        <td>1727</td>
        <td><a href=players.php?pid=56692&edition=5>illannoyin</a></td>
        <td>2</td>
        <td>9761.187</td>
        <td>1044.500</td>
    </tr>
    <tr>
        <td>1728</td>
        <td><a href=players.php?pid=11605&edition=5>Enginebeer2021</a></td>
        <td>2</td>
        <td>9761.293</td>
        <td>1048.500</td>
    </tr>
    <tr>
        <td>1729</td>
        <td><a href=players.php?pid=2639&edition=5>Bigley_</a></td>
        <td>2</td>
        <td>9761.307</td>
        <td>1049.000</td>
    </tr>
    <tr>
        <td>1730</td>
        <td><a href=players.php?pid=12337&edition=5>E-yen</a></td>
        <td>2</td>
        <td>9761.320</td>
        <td>1049.500</td>
    </tr>
    <tr>
        <td>1731</td>
        <td><a href=players.php?pid=66146&edition=5>ProximatePuma</a></td>
        <td>2</td>
        <td>9761.347</td>
        <td>1050.500</td>
    </tr>
    <tr>
        <td>1732</td>
        <td><a href=players.php?pid=52514&edition=5>uncle..iroh..</a></td>
        <td>2</td>
        <td>9761.467</td>
        <td>1055.000</td>
    </tr>
    <tr>
        <td>1733</td>
        <td><a href=players.php?pid=53828&edition=5>F1Crisp</a></td>
        <td>2</td>
        <td>9761.493</td>
        <td>1056.000</td>
    </tr>
    <tr>
        <td>1734</td>
        <td><a href=players.php?pid=66788&edition=5>itgalex</a></td>
        <td>2</td>
        <td>9761.520</td>
        <td>1057.000</td>
    </tr>
    <tr>
        <td>1735</td>
        <td><a href=players.php?pid=66309&edition=5>Moriat-75</a></td>
        <td>2</td>
        <td>9761.547</td>
        <td>1058.000</td>
    </tr>
    <tr>
        <td>1736</td>
        <td><a href=players.php?pid=19714&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;</span><span
                    style='color:#6600cc;font-weight:bold;'>RahWo</span></a></td>
        <td>2</td>
        <td>9761.627</td>
        <td>1061.000</td>
    </tr>
    <tr>
        <td>1737</td>
        <td><a href=players.php?pid=5867&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;C0D3X</span></a></td>
        <td>2</td>
        <td>9761.800</td>
        <td>1067.500</td>
    </tr>
    <tr>
        <td>1738</td>
        <td><a href=players.php?pid=66960&edition=5>Polsku</a></td>
        <td>2</td>
        <td>9761.907</td>
        <td>1071.500</td>
    </tr>
    <tr>
        <td>1739</td>
        <td><a href=players.php?pid=69757&edition=5>Wernbe</a></td>
        <td>2</td>
        <td>9761.933</td>
        <td>1072.500</td>
    </tr>
    <tr>
        <td>1740</td>
        <td><a href=players.php?pid=67558&edition=5>FelixSffS08</a></td>
        <td>2</td>
        <td>9762.267</td>
        <td>1085.000</td>
    </tr>
    <tr>
        <td>1741</td>
        <td><a href=players.php?pid=64935&edition=5>SlovakNick</a></td>
        <td>2</td>
        <td>9762.467</td>
        <td>1092.500</td>
    </tr>
    <tr>
        <td>1742</td>
        <td><a href=players.php?pid=65351&edition=5>PIPOxSKYY</a></td>
        <td>2</td>
        <td>9762.587</td>
        <td>1097.000</td>
    </tr>
    <tr>
        <td>1743</td>
        <td><a href=players.php?pid=21842&edition=5>TapewormSemenDrinker</a></td>
        <td>2</td>
        <td>9762.733</td>
        <td>1102.500</td>
    </tr>
    <tr>
        <td>1744</td>
        <td><a href=players.php?pid=40439&edition=5>All&nbsp;Clips&nbsp;|&nbsp;Lluidon</a></td>
        <td>2</td>
        <td>9762.773</td>
        <td>1104.000</td>
    </tr>
    <tr>
        <td>1745</td>
        <td><a href=players.php?pid=39133&edition=5>ionuzzu_123</a></td>
        <td>2</td>
        <td>9762.827</td>
        <td>1106.000</td>
    </tr>
    <tr>
        <td>1746</td>
        <td><a href=players.php?pid=38145&edition=5><span style='color:#33ff00;font-weight:bold;'>C</span><span
                    style='color:#44ee00;font-weight:bold;'>r</span><span
                    style='color:#55ee00;font-weight:bold;'>a</span><span
                    style='color:#55dd00;font-weight:bold;'>z</span><span
                    style='color:#66cc00;font-weight:bold;'>y</span><span
                    style='color:#66cc00;font-weight:bold;'>M</span><span
                    style='color:#55bb00;font-weight:bold;'>e</span><span
                    style='color:#339900;font-weight:bold;'>l</span><span
                    style='color:#228800;font-weight:bold;'>o</span><span
                    style='color:#006600;font-weight:bold;'>n</span></a></td>
        <td>2</td>
        <td>9762.893</td>
        <td>1108.500</td>
    </tr>
    <tr>
        <td>1747</td>
        <td><a href=players.php?pid=33850&edition=5>Uzknown</a></td>
        <td>2</td>
        <td>9762.973</td>
        <td>1111.500</td>
    </tr>
    <tr>
        <td>1748</td>
        <td><a href=players.php?pid=47086&edition=5>Rarit.UwU</a></td>
        <td>2</td>
        <td>9763.053</td>
        <td>1114.500</td>
    </tr>
    <tr>
        <td>1749</td>
        <td><a href=players.php?pid=68375&edition=5>JuanBoblo</a></td>
        <td>2</td>
        <td>9763.107</td>
        <td>1116.500</td>
    </tr>
    <tr>
        <td>1750</td>
        <td><a href=players.php?pid=66689&edition=5>Nionck</a></td>
        <td>2</td>
        <td>9763.200</td>
        <td>1120.000</td>
    </tr>
    <tr>
        <td>1751</td>
        <td><a href=players.php?pid=47805&edition=5>Simber1</a></td>
        <td>2</td>
        <td>9763.200</td>
        <td>1120.000</td>
    </tr>
    <tr>
        <td>1752</td>
        <td><a href=players.php?pid=63793&edition=5><span style='color:#6600cc;'>P</span><span
                    style='color:#7700dd;'>i</span><span style='color:#8800ee;'>k</span><span
                    style='color:#9900ff;'>l</span><span style='color:#9900ff;'>d</span><span
                    style='color:#bb22ff;'>o</span><span style='color:#dd44ff;'>g</span><span
                    style='color:#ff66ff;'>e</span></a></td>
        <td>2</td>
        <td>9763.200</td>
        <td>1120.000</td>
    </tr>
    <tr>
        <td>1753</td>
        <td><a href=players.php?pid=70653&edition=5>ArisakaT99</a></td>
        <td>2</td>
        <td>9763.267</td>
        <td>1122.500</td>
    </tr>
    <tr>
        <td>1754</td>
        <td><a href=players.php?pid=7408&edition=5>Jenzu_</a></td>
        <td>2</td>
        <td>9763.280</td>
        <td>1123.000</td>
    </tr>
    <tr>
        <td>1755</td>
        <td><a href=players.php?pid=69535&edition=5><span style='color:#6633cc;'>S</span><span
                    style='color:#442288;'>h</span><span style='color:#221144;'>o</span><span
                    style='color:#000000;'>w</span><span style='color:#000000;'>o</span><span
                    style='color:#221144;'>r</span><span style='color:#442288;'>t</span><span
                    style='color:#6633cc;'>y</span></a></td>
        <td>2</td>
        <td>9763.520</td>
        <td>1132.000</td>
    </tr>
    <tr>
        <td>1756</td>
        <td><a href=players.php?pid=54686&edition=5><span style='color:#6600cc;'>T</span><span
                    style='color:#7700dd;'>h</span><span style='color:#8800ee;'>r</span><span
                    style='color:#9900ff;'>y</span><span style='color:#9900ff;'>w</span><span
                    style='color:#bb00ff;'>y</span><span style='color:#cc00ff;'>n</span></a></td>
        <td>2</td>
        <td>9763.560</td>
        <td>1133.500</td>
    </tr>
    <tr>
        <td>1757</td>
        <td><a href=players.php?pid=41545&edition=5>Hey_Blinkin.</a></td>
        <td>2</td>
        <td>9763.640</td>
        <td>1136.500</td>
    </tr>
    <tr>
        <td>1758</td>
        <td><a href=players.php?pid=62838&edition=5>LurkNurk</a></td>
        <td>2</td>
        <td>9763.800</td>
        <td>1142.500</td>
    </tr>
    <tr>
        <td>1759</td>
        <td><a href=players.php?pid=66181&edition=5><span style='color:#ffccdd;'>Jon</span><span
                    style='color:#888888;'>aphan</span></a></td>
        <td>2</td>
        <td>9763.800</td>
        <td>1142.500</td>
    </tr>
    <tr>
        <td>1760</td>
        <td><a href=players.php?pid=57060&edition=5>GamesInspector</a></td>
        <td>2</td>
        <td>9763.813</td>
        <td>1143.000</td>
    </tr>
    <tr>
        <td>1761</td>
        <td><a href=players.php?pid=44613&edition=5>xkoshy</a></td>
        <td>2</td>
        <td>9763.933</td>
        <td>1147.500</td>
    </tr>
    <tr>
        <td>1762</td>
        <td><a href=players.php?pid=55013&edition=5>Renday</a></td>
        <td>2</td>
        <td>9764.027</td>
        <td>1151.000</td>
    </tr>
    <tr>
        <td>1763</td>
        <td><a href=players.php?pid=51948&edition=5>vulkaanruben</a></td>
        <td>2</td>
        <td>9764.080</td>
        <td>1153.000</td>
    </tr>
    <tr>
        <td>1764</td>
        <td><a href=players.php?pid=39869&edition=5>SqualidBongo965</a></td>
        <td>2</td>
        <td>9764.147</td>
        <td>1155.500</td>
    </tr>
    <tr>
        <td>1765</td>
        <td><a href=players.php?pid=66500&edition=5>adam.sejo</a></td>
        <td>2</td>
        <td>9764.173</td>
        <td>1156.500</td>
    </tr>
    <tr>
        <td>1766</td>
        <td><a href=players.php?pid=68491&edition=5>KinGPonin</a></td>
        <td>2</td>
        <td>9764.227</td>
        <td>1158.500</td>
    </tr>
    <tr>
        <td>1767</td>
        <td><a href=players.php?pid=25324&edition=5>Yerkling</a></td>
        <td>2</td>
        <td>9764.267</td>
        <td>1160.000</td>
    </tr>
    <tr>
        <td>1768</td>
        <td><a href=players.php?pid=57271&edition=5>Cookiedough5059</a></td>
        <td>2</td>
        <td>9764.333</td>
        <td>1162.500</td>
    </tr>
    <tr>
        <td>1769</td>
        <td><a href=players.php?pid=68475&edition=5>Jupezzz</a></td>
        <td>2</td>
        <td>9764.373</td>
        <td>1164.000</td>
    </tr>
    <tr>
        <td>1770</td>
        <td><a href=players.php?pid=71007&edition=5>Bobs_Bakery</a></td>
        <td>2</td>
        <td>9764.427</td>
        <td>1166.000</td>
    </tr>
    <tr>
        <td>1771</td>
        <td><a href=players.php?pid=6904&edition=5>B2&nbsp;Frechdachs</a></td>
        <td>2</td>
        <td>9765.280</td>
        <td>1198.000</td>
    </tr>
    <tr>
        <td>1772</td>
        <td><a href=players.php?pid=69876&edition=5>M3TAWORLDPEACE</a></td>
        <td>2</td>
        <td>9765.360</td>
        <td>1201.000</td>
    </tr>
    <tr>
        <td>1773</td>
        <td><a href=players.php?pid=42190&edition=5><span
                    style='color:#3333ff;font-style:italic;font-weight:bold;'>Adamo</span></a></td>
        <td>2</td>
        <td>9765.373</td>
        <td>1201.500</td>
    </tr>
    <tr>
        <td>1774</td>
        <td><a href=players.php?pid=72426&edition=5>Euphyllia-</a></td>
        <td>2</td>
        <td>9765.427</td>
        <td>1203.500</td>
    </tr>
    <tr>
        <td>1775</td>
        <td><a href=players.php?pid=55882&edition=5>TheCthu</a></td>
        <td>2</td>
        <td>9765.720</td>
        <td>1214.500</td>
    </tr>
    <tr>
        <td>1776</td>
        <td><a href=players.php?pid=57041&edition=5>Ben_U_Ron</a></td>
        <td>2</td>
        <td>9765.773</td>
        <td>1216.500</td>
    </tr>
    <tr>
        <td>1777</td>
        <td><a href=players.php?pid=71212&edition=5>Kalmindon_</a></td>
        <td>2</td>
        <td>9766.293</td>
        <td>1236.000</td>
    </tr>
    <tr>
        <td>1778</td>
        <td><a href=players.php?pid=8967&edition=5>gooshon1221</a></td>
        <td>2</td>
        <td>9766.440</td>
        <td>1241.500</td>
    </tr>
    <tr>
        <td>1779</td>
        <td><a href=players.php?pid=65623&edition=5>Adragon671</a></td>
        <td>2</td>
        <td>9767.093</td>
        <td>1266.000</td>
    </tr>
    <tr>
        <td>1780</td>
        <td><a href=players.php?pid=72167&edition=5>Psi-Kick</a></td>
        <td>2</td>
        <td>9767.280</td>
        <td>1273.000</td>
    </tr>
    <tr>
        <td>1781</td>
        <td><a href=players.php?pid=53904&edition=5>BobTMNF</a></td>
        <td>2</td>
        <td>9767.320</td>
        <td>1274.500</td>
    </tr>
    <tr>
        <td>1782</td>
        <td><a href=players.php?pid=50216&edition=5>NorthhRL</a></td>
        <td>2</td>
        <td>9767.440</td>
        <td>1279.000</td>
    </tr>
    <tr>
        <td>1783</td>
        <td><a href=players.php?pid=66459&edition=5>Yolobrim</a></td>
        <td>2</td>
        <td>9767.560</td>
        <td>1283.500</td>
    </tr>
    <tr>
        <td>1784</td>
        <td><a href=players.php?pid=70441&edition=5>AesrivDivier</a></td>
        <td>2</td>
        <td>9767.693</td>
        <td>1288.500</td>
    </tr>
    <tr>
        <td>1785</td>
        <td><a href=players.php?pid=59054&edition=5>ppaappii06</a></td>
        <td>2</td>
        <td>9767.693</td>
        <td>1288.500</td>
    </tr>
    <tr>
        <td>1786</td>
        <td><a href=players.php?pid=12639&edition=5><span style='color:#331111;font-weight:bold;'>A</span><span
                    style='color:#885533;font-weight:bold;'>v</span><span
                    style='color:#442200;font-weight:bold;'>e</span><span
                    style='color:#224455;font-weight:bold;'>r</span><span
                    style='color:#331111;font-weight:bold;'>i</span><span
                    style='color:#885533;font-weight:bold;'>g</span><span
                    style='color:#442200;font-weight:bold;'>i</span><span
                    style='color:#224455;font-weight:bold;'>n</span><span
                    style='color:#331111;font-weight:bold;'>e</span><span
                    style='color:#885533;font-weight:bold;'>s</span></a></td>
        <td>2</td>
        <td>9767.960</td>
        <td>1298.500</td>
    </tr>
    <tr>
        <td>1787</td>
        <td><a href=players.php?pid=68996&edition=5>NuclearPotat</a></td>
        <td>2</td>
        <td>9768.053</td>
        <td>1302.000</td>
    </tr>
    <tr>
        <td>1788</td>
        <td><a href=players.php?pid=71634&edition=5>HyperNovaTM</a></td>
        <td>2</td>
        <td>9768.173</td>
        <td>1306.500</td>
    </tr>
    <tr>
        <td>1789</td>
        <td><a href=players.php?pid=9472&edition=5>Shivaxi</a></td>
        <td>2</td>
        <td>9768.280</td>
        <td>1310.500</td>
    </tr>
    <tr>
        <td>1790</td>
        <td><a href=players.php?pid=52086&edition=5>mmmmmamooml</a></td>
        <td>2</td>
        <td>9768.613</td>
        <td>1323.000</td>
    </tr>
    <tr>
        <td>1791</td>
        <td><a href=players.php?pid=30755&edition=5>Fuzuzil</a></td>
        <td>2</td>
        <td>9768.773</td>
        <td>1329.000</td>
    </tr>
    <tr>
        <td>1792</td>
        <td><a href=players.php?pid=37374&edition=5>NeoMidas</a></td>
        <td>2</td>
        <td>9768.800</td>
        <td>1330.000</td>
    </tr>
    <tr>
        <td>1793</td>
        <td><a href=players.php?pid=32092&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>TheVox</span></a></td>
        <td>2</td>
        <td>9768.800</td>
        <td>1330.000</td>
    </tr>
    <tr>
        <td>1794</td>
        <td><a href=players.php?pid=1326&edition=5>carapp</a></td>
        <td>2</td>
        <td>9769.013</td>
        <td>1338.000</td>
    </tr>
    <tr>
        <td>1795</td>
        <td><a href=players.php?pid=68027&edition=5><span
                    style='color:#00ff00;font-style:italic;font-weight:bold;'>G</span><span
                    style='color:#33ff33;font-style:italic;font-weight:bold;'>a</span><span
                    style='color:#66ff66;font-style:italic;font-weight:bold;'>a</span><span
                    style='color:#99ff99;font-style:italic;font-weight:bold;'>s</span><span
                    style='color:#ccffcc;font-style:italic;font-weight:bold;'>l</span><span
                    style='color:#ffffff;font-style:italic;font-weight:bold;'>y</span></a></td>
        <td>2</td>
        <td>9769.027</td>
        <td>1338.500</td>
    </tr>
    <tr>
        <td>1796</td>
        <td><a href=players.php?pid=57677&edition=5>Foxiiihh</a></td>
        <td>2</td>
        <td>9769.053</td>
        <td>1339.500</td>
    </tr>
    <tr>
        <td>1797</td>
        <td><a href=players.php?pid=51589&edition=5>bakedato</a></td>
        <td>2</td>
        <td>9769.187</td>
        <td>1344.500</td>
    </tr>
    <tr>
        <td>1798</td>
        <td><a href=players.php?pid=32785&edition=5>QuentinTM15</a></td>
        <td>2</td>
        <td>9769.253</td>
        <td>1347.000</td>
    </tr>
    <tr>
        <td>1799</td>
        <td><a href=players.php?pid=68033&edition=5>Soxeer</a></td>
        <td>2</td>
        <td>9769.320</td>
        <td>1349.500</td>
    </tr>
    <tr>
        <td>1800</td>
        <td><a href=players.php?pid=60089&edition=5>ErasedReaperTM</a></td>
        <td>2</td>
        <td>9769.480</td>
        <td>1355.500</td>
    </tr>
    <tr>
        <td>1801</td>
        <td><a href=players.php?pid=70835&edition=5>ah0nen41</a></td>
        <td>2</td>
        <td>9769.613</td>
        <td>1360.500</td>
    </tr>
    <tr>
        <td>1802</td>
        <td><a href=players.php?pid=24415&edition=5>Checkerz</a></td>
        <td>2</td>
        <td>9769.667</td>
        <td>1362.500</td>
    </tr>
    <tr>
        <td>1803</td>
        <td><a href=players.php?pid=65436&edition=5><span style='color:#33ffff;'>a</span><span
                    style='color:#99ffff;'>l</span><span style='color:#ffffff;'>l</span><span
                    style='color:#ffffff;'>u</span><span style='color:#aaeeee;'>f</span></a></td>
        <td>2</td>
        <td>9769.747</td>
        <td>1365.500</td>
    </tr>
    <tr>
        <td>1804</td>
        <td><a href=players.php?pid=64844&edition=5>th3bomb93</a></td>
        <td>2</td>
        <td>9769.840</td>
        <td>1369.000</td>
    </tr>
    <tr>
        <td>1805</td>
        <td><a href=players.php?pid=35759&edition=5>scragouli</a></td>
        <td>2</td>
        <td>9769.853</td>
        <td>1369.500</td>
    </tr>
    <tr>
        <td>1806</td>
        <td><a href=players.php?pid=64719&edition=5>Chimerica</a></td>
        <td>2</td>
        <td>9769.933</td>
        <td>1372.500</td>
    </tr>
    <tr>
        <td>1807</td>
        <td><a href=players.php?pid=54411&edition=5>Itscamcar</a></td>
        <td>2</td>
        <td>9770.413</td>
        <td>1390.500</td>
    </tr>
    <tr>
        <td>1808</td>
        <td><a href=players.php?pid=30049&edition=5>Choca_21</a></td>
        <td>2</td>
        <td>9770.827</td>
        <td>1406.000</td>
    </tr>
    <tr>
        <td>1809</td>
        <td><a href=players.php?pid=69123&edition=5>Awolllll</a></td>
        <td>2</td>
        <td>9771.600</td>
        <td>1435.000</td>
    </tr>
    <tr>
        <td>1810</td>
        <td><a href=players.php?pid=52266&edition=5>PoGueTM</a></td>
        <td>2</td>
        <td>9772.600</td>
        <td>1472.500</td>
    </tr>
    <tr>
        <td>1811</td>
        <td><a href=players.php?pid=71077&edition=5>zAbsIn2023LUL</a></td>
        <td>2</td>
        <td>9772.867</td>
        <td>1482.500</td>
    </tr>
    <tr>
        <td>1812</td>
        <td><a href=players.php?pid=53131&edition=5><span style='color:#ff0000;'>Just</span><span
                    style='color:#ffbb00;'>the</span><span style='color:#ffff00;'>K98!!!</span></a></td>
        <td>2</td>
        <td>9773.027</td>
        <td>1488.500</td>
    </tr>
    <tr>
        <td>1813</td>
        <td><a href=players.php?pid=60577&edition=5>DrPigz</a></td>
        <td>2</td>
        <td>9773.827</td>
        <td>1518.500</td>
    </tr>
    <tr>
        <td>1814</td>
        <td><a href=players.php?pid=66825&edition=5>thismustbeagame</a></td>
        <td>2</td>
        <td>9774.000</td>
        <td>1525.000</td>
    </tr>
    <tr>
        <td>1815</td>
        <td><a href=players.php?pid=33127&edition=5>KTBUnlock</a></td>
        <td>2</td>
        <td>9774.200</td>
        <td>1532.500</td>
    </tr>
    <tr>
        <td>1816</td>
        <td><a href=players.php?pid=71263&edition=5>Kran</a></td>
        <td>2</td>
        <td>9774.293</td>
        <td>1536.000</td>
    </tr>
    <tr>
        <td>1817</td>
        <td><a href=players.php?pid=48638&edition=5><span style='color:#66ddff;'>as</span><span
                    style='color:#ffbbcc;'>tr</span><span style='color:#ffffff;'>io</span><span
                    style='color:#ffbbcc;'>n</span><span style='color:#66ddff;'>ic</span></a></td>
        <td>2</td>
        <td>9775.173</td>
        <td>1569.000</td>
    </tr>
    <tr>
        <td>1818</td>
        <td><a href=players.php?pid=48629&edition=5>WarmFace_ZERO</a></td>
        <td>2</td>
        <td>9776.227</td>
        <td>1608.500</td>
    </tr>
    <tr>
        <td>1819</td>
        <td><a href=players.php?pid=66648&edition=5>VGabrielbr</a></td>
        <td>2</td>
        <td>9777.640</td>
        <td>1661.500</td>
    </tr>
    <tr>
        <td>1820</td>
        <td><a href=players.php?pid=33587&edition=5>GC</a></td>
        <td>2</td>
        <td>9778.320</td>
        <td>1687.000</td>
    </tr>
    <tr>
        <td>1821</td>
        <td><a href=players.php?pid=69277&edition=5>322&nbsp;Technology</a></td>
        <td>1</td>
        <td>9866.680</td>
        <td>1.000</td>
    </tr>
    <tr>
        <td>1822</td>
        <td><a href=players.php?pid=7684&edition=5>Pantheory</a></td>
        <td>1</td>
        <td>9866.680</td>
        <td>1.000</td>
    </tr>
    <tr>
        <td>1823</td>
        <td><a href=players.php?pid=24313&edition=5>Patriam</a></td>
        <td>1</td>
        <td>9866.693</td>
        <td>2.000</td>
    </tr>
    <tr>
        <td>1824</td>
        <td><a href=players.php?pid=64379&edition=5>btw-_-jnn</a></td>
        <td>1</td>
        <td>9866.707</td>
        <td>3.000</td>
    </tr>
    <tr>
        <td>1825</td>
        <td><a href=players.php?pid=15282&edition=5>Ach1oto</a></td>
        <td>1</td>
        <td>9866.707</td>
        <td>3.000</td>
    </tr>
    <tr>
        <td>1826</td>
        <td><a href=players.php?pid=14373&edition=5>Susuwi</a></td>
        <td>1</td>
        <td>9866.720</td>
        <td>4.000</td>
    </tr>
    <tr>
        <td>1827</td>
        <td><a href=players.php?pid=67644&edition=5>Geslie</a></td>
        <td>1</td>
        <td>9866.720</td>
        <td>4.000</td>
    </tr>
    <tr>
        <td>1828</td>
        <td><a href=players.php?pid=66876&edition=5><span style='color:#ffbbff;font-style:italic;'>i</span><span
                    style='color:#ff99ff;font-style:italic;'>t</span><span
                    style='color:#ee77ff;font-style:italic;'>s</span><span
                    style='color:#ee77ff;font-style:italic;'>Ɲ</span><span
                    style='color:#cc66dd;font-style:italic;'>i</span><span
                    style='color:#aa55bb;font-style:italic;'>v</span><span
                    style='color:#884499;font-style:italic;'>a</span></a></td>
        <td>1</td>
        <td>9866.733</td>
        <td>5.000</td>
    </tr>
    <tr>
        <td>1829</td>
        <td><a href=players.php?pid=6977&edition=5>User.45</a></td>
        <td>1</td>
        <td>9866.733</td>
        <td>5.000</td>
    </tr>
    <tr>
        <td>1830</td>
        <td><a href=players.php?pid=3109&edition=5>Sapirlipopette</a></td>
        <td>1</td>
        <td>9866.733</td>
        <td>5.000</td>
    </tr>
    <tr>
        <td>1831</td>
        <td><a href=players.php?pid=72567&edition=5>djm0321</a></td>
        <td>1</td>
        <td>9866.747</td>
        <td>6.000</td>
    </tr>
    <tr>
        <td>1832</td>
        <td><a href=players.php?pid=50290&edition=5>Icyrain_</a></td>
        <td>1</td>
        <td>9866.773</td>
        <td>8.000</td>
    </tr>
    <tr>
        <td>1833</td>
        <td><a href=players.php?pid=26417&edition=5>Mirkorino</a></td>
        <td>1</td>
        <td>9866.773</td>
        <td>8.000</td>
    </tr>
    <tr>
        <td>1834</td>
        <td><a href=players.php?pid=37326&edition=5>Aughlnal</a></td>
        <td>1</td>
        <td>9866.813</td>
        <td>11.000</td>
    </tr>
    <tr>
        <td>1835</td>
        <td><a href=players.php?pid=71133&edition=5>dimawallhacks67</a></td>
        <td>1</td>
        <td>9866.827</td>
        <td>12.000</td>
    </tr>
    <tr>
        <td>1836</td>
        <td><a href=players.php?pid=66471&edition=5>Deew_Wi</a></td>
        <td>1</td>
        <td>9866.840</td>
        <td>13.000</td>
    </tr>
    <tr>
        <td>1837</td>
        <td><a href=players.php?pid=1063&edition=5>Takuge9</a></td>
        <td>1</td>
        <td>9866.867</td>
        <td>15.000</td>
    </tr>
    <tr>
        <td>1838</td>
        <td><a href=players.php?pid=49484&edition=5>YEET&nbsp;MASTER</a></td>
        <td>1</td>
        <td>9866.880</td>
        <td>16.000</td>
    </tr>
    <tr>
        <td>1839</td>
        <td><a href=players.php?pid=4414&edition=5>RedLinesNative</a></td>
        <td>1</td>
        <td>9866.893</td>
        <td>17.000</td>
    </tr>
    <tr>
        <td>1840</td>
        <td><a href=players.php?pid=32691&edition=5>Juphie</a></td>
        <td>1</td>
        <td>9866.893</td>
        <td>17.000</td>
    </tr>
    <tr>
        <td>1841</td>
        <td><a href=players.php?pid=68978&edition=5>BurntT04st3</a></td>
        <td>1</td>
        <td>9866.907</td>
        <td>18.000</td>
    </tr>
    <tr>
        <td>1842</td>
        <td><a href=players.php?pid=48276&edition=5>Occams_LazerTM</a></td>
        <td>1</td>
        <td>9866.907</td>
        <td>18.000</td>
    </tr>
    <tr>
        <td>1843</td>
        <td><a href=players.php?pid=16575&edition=5>leg_eater</a></td>
        <td>1</td>
        <td>9866.907</td>
        <td>18.000</td>
    </tr>
    <tr>
        <td>1844</td>
        <td><a href=players.php?pid=68804&edition=5>ILLUSIUUM</a></td>
        <td>1</td>
        <td>9866.920</td>
        <td>19.000</td>
    </tr>
    <tr>
        <td>1845</td>
        <td><a href=players.php?pid=70787&edition=5>DiePvPJacke</a></td>
        <td>1</td>
        <td>9866.933</td>
        <td>20.000</td>
    </tr>
    <tr>
        <td>1846</td>
        <td><a href=players.php?pid=30082&edition=5><span style='color:#33ff00;'>r</span><span
                    style='color:#66ff44;'>o</span><span style='color:#99ff88;'>b</span><span
                    style='color:#ccffbb;'>b</span><span style='color:#ffffff;'>y</span><span
                    style='color:#ffffff;'>n</span><span style='color:#ffdddd;'>a</span><span
                    style='color:#ffbbbb;'>t</span>0<span style='color:#ff6666;'>r</span></a></td>
        <td>1</td>
        <td>9866.960</td>
        <td>22.000</td>
    </tr>
    <tr>
        <td>1847</td>
        <td><a href=players.php?pid=48559&edition=5>mcKjeltring</a></td>
        <td>1</td>
        <td>9866.960</td>
        <td>22.000</td>
    </tr>
    <tr>
        <td>1848</td>
        <td><a href=players.php?pid=43767&edition=5>azuraine</a></td>
        <td>1</td>
        <td>9866.973</td>
        <td>23.000</td>
    </tr>
    <tr>
        <td>1849</td>
        <td><a href=players.php?pid=69330&edition=5><span style='color:#006600;'>S</span><span
                    style='color:#008800;'>e</span><span style='color:#009900;'>r</span><span
                    style='color:#00cc00;'>f</span><span style='color:#ffffff;'>Lesser</span></a></td>
        <td>1</td>
        <td>9866.973</td>
        <td>23.000</td>
    </tr>
    <tr>
        <td>1850</td>
        <td><a href=players.php?pid=2580&edition=5>el_pent</a></td>
        <td>1</td>
        <td>9867.040</td>
        <td>28.000</td>
    </tr>
    <tr>
        <td>1851</td>
        <td><a href=players.php?pid=36146&edition=5>Aziz_PoLo</a></td>
        <td>1</td>
        <td>9867.107</td>
        <td>33.000</td>
    </tr>
    <tr>
        <td>1852</td>
        <td><a href=players.php?pid=11774&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;NickSow</span></a></td>
        <td>1</td>
        <td>9867.120</td>
        <td>34.000</td>
    </tr>
    <tr>
        <td>1853</td>
        <td><a href=players.php?pid=47407&edition=5>Vingers_</a></td>
        <td>1</td>
        <td>9867.120</td>
        <td>34.000</td>
    </tr>
    <tr>
        <td>1854</td>
        <td><a href=players.php?pid=38112&edition=5>Sidal_08</a></td>
        <td>1</td>
        <td>9867.133</td>
        <td>35.000</td>
    </tr>
    <tr>
        <td>1855</td>
        <td><a href=players.php?pid=52749&edition=5>b<span
                    style='color:#ff00ff;font-style:italic;'>&nbsp;POULE&nbsp;|&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;'>&nbsp;Fenphix&nbsp;</span></a></td>
        <td>1</td>
        <td>9867.173</td>
        <td>38.000</td>
    </tr>
    <tr>
        <td>1856</td>
        <td><a href=players.php?pid=67762&edition=5>keidis1998</a></td>
        <td>1</td>
        <td>9867.227</td>
        <td>42.000</td>
    </tr>
    <tr>
        <td>1857</td>
        <td><a href=players.php?pid=51343&edition=5>Apfeilbaum</a></td>
        <td>1</td>
        <td>9867.253</td>
        <td>44.000</td>
    </tr>
    <tr>
        <td>1858</td>
        <td><a href=players.php?pid=62901&edition=5>Unibus</a></td>
        <td>1</td>
        <td>9867.320</td>
        <td>49.000</td>
    </tr>
    <tr>
        <td>1859</td>
        <td><a href=players.php?pid=30066&edition=5>NinjaPony1337</a></td>
        <td>1</td>
        <td>9867.320</td>
        <td>49.000</td>
    </tr>
    <tr>
        <td>1860</td>
        <td><a href=players.php?pid=52525&edition=5>TheChief_TM</a></td>
        <td>1</td>
        <td>9867.333</td>
        <td>50.000</td>
    </tr>
    <tr>
        <td>1861</td>
        <td><a href=players.php?pid=72215&edition=5>Silencemove</a></td>
        <td>1</td>
        <td>9867.360</td>
        <td>52.000</td>
    </tr>
    <tr>
        <td>1862</td>
        <td><a href=players.php?pid=45297&edition=5>Chabdi</a></td>
        <td>1</td>
        <td>9867.373</td>
        <td>53.000</td>
    </tr>
    <tr>
        <td>1863</td>
        <td><a href=players.php?pid=32350&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;galetteso6&nbsp;&quot;</span></a></td>
        <td>1</td>
        <td>9867.400</td>
        <td>55.000</td>
    </tr>
    <tr>
        <td>1864</td>
        <td><a href=players.php?pid=9522&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Poro</span></a></td>
        <td>1</td>
        <td>9867.453</td>
        <td>59.000</td>
    </tr>
    <tr>
        <td>1865</td>
        <td><a href=players.php?pid=67800&edition=5>DJ_KhaledGaming</a></td>
        <td>1</td>
        <td>9867.453</td>
        <td>59.000</td>
    </tr>
    <tr>
        <td>1866</td>
        <td><a href=players.php?pid=58359&edition=5>TOK_non</a></td>
        <td>1</td>
        <td>9867.520</td>
        <td>64.000</td>
    </tr>
    <tr>
        <td>1867</td>
        <td><a href=players.php?pid=30532&edition=5>Taczuszka</a></td>
        <td>1</td>
        <td>9867.533</td>
        <td>65.000</td>
    </tr>
    <tr>
        <td>1868</td>
        <td><a href=players.php?pid=61624&edition=5>iFusical</a></td>
        <td>1</td>
        <td>9867.560</td>
        <td>67.000</td>
    </tr>
    <tr>
        <td>1869</td>
        <td><a href=players.php?pid=32228&edition=5>HrAnderen</a></td>
        <td>1</td>
        <td>9867.560</td>
        <td>67.000</td>
    </tr>
    <tr>
        <td>1870</td>
        <td><a href=players.php?pid=9024&edition=5>xifos</a></td>
        <td>1</td>
        <td>9867.587</td>
        <td>69.000</td>
    </tr>
    <tr>
        <td>1871</td>
        <td><a href=players.php?pid=68282&edition=5>Sparkyi_TM</a></td>
        <td>1</td>
        <td>9867.613</td>
        <td>71.000</td>
    </tr>
    <tr>
        <td>1872</td>
        <td><a href=players.php?pid=62355&edition=5>GOTCHA34</a></td>
        <td>1</td>
        <td>9867.627</td>
        <td>72.000</td>
    </tr>
    <tr>
        <td>1873</td>
        <td><a href=players.php?pid=69952&edition=5><span style='color:#dd0000;font-style:italic;'>&rho;</span><span
                    style='color:#cc0000;font-style:italic;'>u</span><span
                    style='color:#aa0000;font-style:italic;'>l</span><span
                    style='color:#990000;font-style:italic;'>s</span><span
                    style='color:#880000;font-style:italic;'>e</span><span
                    style='color:#000000;font-style:italic;'>.</span><span
                    style='color:#0000ff;font-style:italic;'>Rugbyab</span></a></td>
        <td>1</td>
        <td>9867.640</td>
        <td>73.000</td>
    </tr>
    <tr>
        <td>1874</td>
        <td><a href=players.php?pid=46576&edition=5>LunienTM</a></td>
        <td>1</td>
        <td>9867.640</td>
        <td>73.000</td>
    </tr>
    <tr>
        <td>1875</td>
        <td><a href=players.php?pid=42926&edition=5>Ping-elek</a></td>
        <td>1</td>
        <td>9867.653</td>
        <td>74.000</td>
    </tr>
    <tr>
        <td>1876</td>
        <td><a href=players.php?pid=6496&edition=5>b<span style='color:#ff9922;font-weight:bold;'>YUKEMASTER</span></a>
        </td>
        <td>1</td>
        <td>9867.667</td>
        <td>75.000</td>
    </tr>
    <tr>
        <td>1877</td>
        <td><a href=players.php?pid=70167&edition=5>kstef30</a></td>
        <td>1</td>
        <td>9867.693</td>
        <td>77.000</td>
    </tr>
    <tr>
        <td>1878</td>
        <td><a href=players.php?pid=14573&edition=5>Anticort</a></td>
        <td>1</td>
        <td>9867.707</td>
        <td>78.000</td>
    </tr>
    <tr>
        <td>1879</td>
        <td><a href=players.php?pid=71715&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;MaJ</span></a></td>
        <td>1</td>
        <td>9867.707</td>
        <td>78.000</td>
    </tr>
    <tr>
        <td>1880</td>
        <td><a href=players.php?pid=67500&edition=5>shady_afterglow</a></td>
        <td>1</td>
        <td>9867.720</td>
        <td>79.000</td>
    </tr>
    <tr>
        <td>1881</td>
        <td><a href=players.php?pid=67318&edition=5>Mnesiq</a></td>
        <td>1</td>
        <td>9867.747</td>
        <td>81.000</td>
    </tr>
    <tr>
        <td>1882</td>
        <td><a href=players.php?pid=53730&edition=5>SwapTM</a></td>
        <td>1</td>
        <td>9867.760</td>
        <td>82.000</td>
    </tr>
    <tr>
        <td>1883</td>
        <td><a href=players.php?pid=68208&edition=5>Pickle_Duck</a></td>
        <td>1</td>
        <td>9867.773</td>
        <td>83.000</td>
    </tr>
    <tr>
        <td>1884</td>
        <td><a href=players.php?pid=49287&edition=5>Luna-Moonfang</a></td>
        <td>1</td>
        <td>9867.773</td>
        <td>83.000</td>
    </tr>
    <tr>
        <td>1885</td>
        <td><a href=players.php?pid=66616&edition=5>DejfMandy</a></td>
        <td>1</td>
        <td>9867.813</td>
        <td>86.000</td>
    </tr>
    <tr>
        <td>1886</td>
        <td><a href=players.php?pid=11291&edition=5>Igrelex</a></td>
        <td>1</td>
        <td>9867.840</td>
        <td>88.000</td>
    </tr>
    <tr>
        <td>1887</td>
        <td><a href=players.php?pid=70152&edition=5>Slach78200</a></td>
        <td>1</td>
        <td>9867.840</td>
        <td>88.000</td>
    </tr>
    <tr>
        <td>1888</td>
        <td><a href=players.php?pid=51271&edition=5>IPraygeToTrees</a></td>
        <td>1</td>
        <td>9867.867</td>
        <td>90.000</td>
    </tr>
    <tr>
        <td>1889</td>
        <td><a href=players.php?pid=15021&edition=5>Cuthalion_TM</a></td>
        <td>1</td>
        <td>9867.893</td>
        <td>92.000</td>
    </tr>
    <tr>
        <td>1890</td>
        <td><a href=players.php?pid=24822&edition=5>Blavok</a></td>
        <td>1</td>
        <td>9867.907</td>
        <td>93.000</td>
    </tr>
    <tr>
        <td>1891</td>
        <td><a href=players.php?pid=50781&edition=5>T0co-TM</a></td>
        <td>1</td>
        <td>9867.907</td>
        <td>93.000</td>
    </tr>
    <tr>
        <td>1892</td>
        <td><a href=players.php?pid=57051&edition=5>Meilo.</a></td>
        <td>1</td>
        <td>9867.947</td>
        <td>96.000</td>
    </tr>
    <tr>
        <td>1893</td>
        <td><a href=players.php?pid=52647&edition=5>mynameisfaran</a></td>
        <td>1</td>
        <td>9867.987</td>
        <td>99.000</td>
    </tr>
    <tr>
        <td>1894</td>
        <td><a href=players.php?pid=2816&edition=5><span style='color:#11dd55;'>gloя</span><span
                    style='color:#11dd55;'>p&nbsp;</span>|&nbsp;<span style='font-style:italic;'>Kcedus</span></a></td>
        <td>1</td>
        <td>9867.987</td>
        <td>99.000</td>
    </tr>
    <tr>
        <td>1895</td>
        <td><a href=players.php?pid=1637&edition=5>thekrecoun</a></td>
        <td>1</td>
        <td>9867.987</td>
        <td>99.000</td>
    </tr>
    <tr>
        <td>1896</td>
        <td><a href=players.php?pid=72066&edition=5>Avextro</a></td>
        <td>1</td>
        <td>9867.987</td>
        <td>99.000</td>
    </tr>
    <tr>
        <td>1897</td>
        <td><a href=players.php?pid=68199&edition=5>DallienDoo</a></td>
        <td>1</td>
        <td>9868.000</td>
        <td>100.000</td>
    </tr>
    <tr>
        <td>1898</td>
        <td><a href=players.php?pid=46546&edition=5><span style='color:#9900ff;'>Л</span><span
                    style='color:#aa00dd;'>İ</span><span style='color:#bb00bb;'>Y</span><span
                    style='color:#cc0099;'>ũ</span><span style='color:#cc0066;'>Ķ</span><span
                    style='color:#dd0044;'>เ</span><span style='color:#ee0022;'>&nbsp;</span><span
                    style='color:#ff0000;'>K</span><span style='color:#ff0000;'>u</span><span
                    style='color:#ff2222;'>r</span><span style='color:#ee4444;'>o</span><span
                    style='color:#ee6666;'>s</span><span style='color:#ee7777;'>h</span><span
                    style='color:#ee9999;'>i</span><span style='color:#ddbbbb;'>r</span><span
                    style='color:#dddddd;'>o</span></a></td>
        <td>1</td>
        <td>9868.013</td>
        <td>101.000</td>
    </tr>
    <tr>
        <td>1899</td>
        <td><a href=players.php?pid=31853&edition=5>Foxtail_Fennec</a></td>
        <td>1</td>
        <td>9868.067</td>
        <td>105.000</td>
    </tr>
    <tr>
        <td>1900</td>
        <td><a href=players.php?pid=66356&edition=5>pandageneral97</a></td>
        <td>1</td>
        <td>9868.067</td>
        <td>105.000</td>
    </tr>
    <tr>
        <td>1901</td>
        <td><a href=players.php?pid=7069&edition=5>GoodOlPing</a></td>
        <td>1</td>
        <td>9868.080</td>
        <td>106.000</td>
    </tr>
    <tr>
        <td>1902</td>
        <td><a href=players.php?pid=26560&edition=5>AAH_Zeaf</a></td>
        <td>1</td>
        <td>9868.093</td>
        <td>107.000</td>
    </tr>
    <tr>
        <td>1903</td>
        <td><a href=players.php?pid=67638&edition=5>N3ekoNii</a></td>
        <td>1</td>
        <td>9868.093</td>
        <td>107.000</td>
    </tr>
    <tr>
        <td>1904</td>
        <td><a href=players.php?pid=14886&edition=5>yutu58</a></td>
        <td>1</td>
        <td>9868.107</td>
        <td>108.000</td>
    </tr>
    <tr>
        <td>1905</td>
        <td><a href=players.php?pid=66324&edition=5>xisken</a></td>
        <td>1</td>
        <td>9868.120</td>
        <td>109.000</td>
    </tr>
    <tr>
        <td>1906</td>
        <td><a href=players.php?pid=7827&edition=5><span style='color:#ffffff;'>Am</span><span
                    style='color:#00ff00;'>a</span><span style='color:#ffffff;'>terasu</span><span
                    style='color:#00ff00;'>!</span></a></td>
        <td>1</td>
        <td>9868.173</td>
        <td>113.000</td>
    </tr>
    <tr>
        <td>1907</td>
        <td><a href=players.php?pid=33231&edition=5>Reddnox</a></td>
        <td>1</td>
        <td>9868.187</td>
        <td>114.000</td>
    </tr>
    <tr>
        <td>1908</td>
        <td><a href=players.php?pid=55124&edition=5>soxpanda</a></td>
        <td>1</td>
        <td>9868.227</td>
        <td>117.000</td>
    </tr>
    <tr>
        <td>1909</td>
        <td><a href=players.php?pid=50933&edition=5>AAAButter</a></td>
        <td>1</td>
        <td>9868.280</td>
        <td>121.000</td>
    </tr>
    <tr>
        <td>1910</td>
        <td><a href=players.php?pid=69750&edition=5><span style='color:#ff9933;'>o</span><span
                    style='color:#ff9955;'>r</span><span style='color:#ff9977;'>a</span><span
                    style='color:#ff9999;'>n</span><span style='color:#ff99bb;'>g</span><span
                    style='color:#ff99dd;'>e</span><span style='color:#ff99ff;'>p</span><span
                    style='color:#ff99ff;'>i</span><span style='color:#ff99ee;'>n</span><span
                    style='color:#ff99dd;'>k</span><span style='color:#ff99bb;'>m</span><span
                    style='color:#ff99aa;'>a</span><span style='color:#ff9999;'>n</span></a></td>
        <td>1</td>
        <td>9868.307</td>
        <td>123.000</td>
    </tr>
    <tr>
        <td>1911</td>
        <td><a href=players.php?pid=67224&edition=5>FeelingSiege</a></td>
        <td>1</td>
        <td>9868.333</td>
        <td>125.000</td>
    </tr>
    <tr>
        <td>1912</td>
        <td><a href=players.php?pid=21169&edition=5>Creepaa__</a></td>
        <td>1</td>
        <td>9868.347</td>
        <td>126.000</td>
    </tr>
    <tr>
        <td>1913</td>
        <td><a href=players.php?pid=72219&edition=5>litmcqueendies</a></td>
        <td>1</td>
        <td>9868.360</td>
        <td>127.000</td>
    </tr>
    <tr>
        <td>1914</td>
        <td><a href=players.php?pid=14569&edition=5>D0yle_</a></td>
        <td>1</td>
        <td>9868.387</td>
        <td>129.000</td>
    </tr>
    <tr>
        <td>1915</td>
        <td><a href=players.php?pid=61912&edition=5>ThreeWheel79851</a></td>
        <td>1</td>
        <td>9868.400</td>
        <td>130.000</td>
    </tr>
    <tr>
        <td>1916</td>
        <td><a href=players.php?pid=26042&edition=5>uol_</a></td>
        <td>1</td>
        <td>9868.413</td>
        <td>131.000</td>
    </tr>
    <tr>
        <td>1917</td>
        <td><a href=players.php?pid=6802&edition=5>InfernoTM.</a></td>
        <td>1</td>
        <td>9868.440</td>
        <td>133.000</td>
    </tr>
    <tr>
        <td>1918</td>
        <td><a href=players.php?pid=42244&edition=5>Qu1ntu</a></td>
        <td>1</td>
        <td>9868.440</td>
        <td>133.000</td>
    </tr>
    <tr>
        <td>1919</td>
        <td><a href=players.php?pid=19933&edition=5>solofarmer</a></td>
        <td>1</td>
        <td>9868.440</td>
        <td>133.000</td>
    </tr>
    <tr>
        <td>1920</td>
        <td><a href=players.php?pid=55183&edition=5>MasteriskPlayed</a></td>
        <td>1</td>
        <td>9868.453</td>
        <td>134.000</td>
    </tr>
    <tr>
        <td>1921</td>
        <td><a href=players.php?pid=67774&edition=5>DadMaster69</a></td>
        <td>1</td>
        <td>9868.480</td>
        <td>136.000</td>
    </tr>
    <tr>
        <td>1922</td>
        <td><a href=players.php?pid=51881&edition=5>BlaiddTM</a></td>
        <td>1</td>
        <td>9868.493</td>
        <td>137.000</td>
    </tr>
    <tr>
        <td>1923</td>
        <td><a href=players.php?pid=35820&edition=5>Nekomito1</a></td>
        <td>1</td>
        <td>9868.533</td>
        <td>140.000</td>
    </tr>
    <tr>
        <td>1924</td>
        <td><a href=players.php?pid=51384&edition=5>LePaing</a></td>
        <td>1</td>
        <td>9868.533</td>
        <td>140.000</td>
    </tr>
    <tr>
        <td>1925</td>
        <td><a href=players.php?pid=71785&edition=5>CheapAsChimps</a></td>
        <td>1</td>
        <td>9868.560</td>
        <td>142.000</td>
    </tr>
    <tr>
        <td>1926</td>
        <td><a href=players.php?pid=65874&edition=5>thxanth1970</a></td>
        <td>1</td>
        <td>9868.587</td>
        <td>144.000</td>
    </tr>
    <tr>
        <td>1927</td>
        <td><a href=players.php?pid=67209&edition=5>Iknu_Deer</a></td>
        <td>1</td>
        <td>9868.600</td>
        <td>145.000</td>
    </tr>
    <tr>
        <td>1928</td>
        <td><a href=players.php?pid=35846&edition=5>CassandraTM</a></td>
        <td>1</td>
        <td>9868.600</td>
        <td>145.000</td>
    </tr>
    <tr>
        <td>1929</td>
        <td><a href=players.php?pid=43421&edition=5>deftlook13</a></td>
        <td>1</td>
        <td>9868.600</td>
        <td>145.000</td>
    </tr>
    <tr>
        <td>1930</td>
        <td><a href=players.php?pid=49651&edition=5>DimmaTM</a></td>
        <td>1</td>
        <td>9868.613</td>
        <td>146.000</td>
    </tr>
    <tr>
        <td>1931</td>
        <td><a href=players.php?pid=66060&edition=5>Dementei</a></td>
        <td>1</td>
        <td>9868.627</td>
        <td>147.000</td>
    </tr>
    <tr>
        <td>1932</td>
        <td><a href=players.php?pid=44089&edition=5>hhuntaa</a></td>
        <td>1</td>
        <td>9868.627</td>
        <td>147.000</td>
    </tr>
    <tr>
        <td>1933</td>
        <td><a href=players.php?pid=56222&edition=5>MyName1sRay</a></td>
        <td>1</td>
        <td>9868.653</td>
        <td>149.000</td>
    </tr>
    <tr>
        <td>1934</td>
        <td><a href=players.php?pid=69165&edition=5>xeap.</a></td>
        <td>1</td>
        <td>9868.667</td>
        <td>150.000</td>
    </tr>
    <tr>
        <td>1935</td>
        <td><a href=players.php?pid=62151&edition=5><span style='color:#ff6600;'>c</span><span
                    style='color:#ffffff;'>o</span><span style='color:#ff6600;'>t｜</span><span
                    style='color:#ffffff;'>&nbsp;sousiytb</span></a></td>
        <td>1</td>
        <td>9868.680</td>
        <td>151.000</td>
    </tr>
    <tr>
        <td>1936</td>
        <td><a href=players.php?pid=59424&edition=5>Slevinox</a></td>
        <td>1</td>
        <td>9868.693</td>
        <td>152.000</td>
    </tr>
    <tr>
        <td>1937</td>
        <td><a href=players.php?pid=30852&edition=5>jtmnf</a></td>
        <td>1</td>
        <td>9868.720</td>
        <td>154.000</td>
    </tr>
    <tr>
        <td>1938</td>
        <td><a href=players.php?pid=20386&edition=5>draggy212</a></td>
        <td>1</td>
        <td>9868.733</td>
        <td>155.000</td>
    </tr>
    <tr>
        <td>1939</td>
        <td><a href=players.php?pid=41915&edition=5>slovenskyvladko</a></td>
        <td>1</td>
        <td>9868.760</td>
        <td>157.000</td>
    </tr>
    <tr>
        <td>1940</td>
        <td><a href=players.php?pid=67991&edition=5>xeandor</a></td>
        <td>1</td>
        <td>9868.773</td>
        <td>158.000</td>
    </tr>
    <tr>
        <td>1941</td>
        <td><a href=players.php?pid=10037&edition=5><span style='color:#ff0000;'>x</span><span
                    style='color:#dd0000;'>B</span><span style='color:#bb0000;'>e</span><span
                    style='color:#990000;'>o</span><span style='color:#660000;'>W</span><span
                    style='color:#440000;'>u</span><span style='color:#220000;'>l</span><span
                    style='color:#000000;'>f</span></a></td>
        <td>1</td>
        <td>9868.773</td>
        <td>158.000</td>
    </tr>
    <tr>
        <td>1942</td>
        <td><a href=players.php?pid=35660&edition=5>L1ghtFrame</a></td>
        <td>1</td>
        <td>9868.813</td>
        <td>161.000</td>
    </tr>
    <tr>
        <td>1943</td>
        <td><a href=players.php?pid=26648&edition=5><span style='color:#ff9900;'>D</span><span
                    style='color:#ffaa11;'>o</span><span style='color:#ffbb11;'>d</span><span
                    style='color:#ffdd22;'>g</span><span style='color:#ffee22;'>e</span><span
                    style='color:#ffff33;'>T</span><span style='color:#ffff33;'>h</span><span
                    style='color:#ffee22;'>e</span><span style='color:#ffdd22;'>D</span><span
                    style='color:#ffbb11;'>u</span><span style='color:#ffaa11;'>c</span><span
                    style='color:#ff9900;'>k</span></a></td>
        <td>1</td>
        <td>9868.840</td>
        <td>163.000</td>
    </tr>
    <tr>
        <td>1944</td>
        <td><a href=players.php?pid=8565&edition=5>B-BoY-T</a></td>
        <td>1</td>
        <td>9868.840</td>
        <td>163.000</td>
    </tr>
    <tr>
        <td>1945</td>
        <td><a href=players.php?pid=39267&edition=5><span style='color:#eeaa22;'>markdeotter</span></a></td>
        <td>1</td>
        <td>9868.853</td>
        <td>164.000</td>
    </tr>
    <tr>
        <td>1946</td>
        <td><a href=players.php?pid=66562&edition=5>nightmaredugtri</a></td>
        <td>1</td>
        <td>9868.893</td>
        <td>167.000</td>
    </tr>
    <tr>
        <td>1947</td>
        <td><a href=players.php?pid=60547&edition=5>Unwaged12</a></td>
        <td>1</td>
        <td>9868.920</td>
        <td>169.000</td>
    </tr>
    <tr>
        <td>1948</td>
        <td><a href=players.php?pid=47680&edition=5>PrivateBlithe69</a></td>
        <td>1</td>
        <td>9868.920</td>
        <td>169.000</td>
    </tr>
    <tr>
        <td>1949</td>
        <td><a href=players.php?pid=66271&edition=5>table_support</a></td>
        <td>1</td>
        <td>9868.933</td>
        <td>170.000</td>
    </tr>
    <tr>
        <td>1950</td>
        <td><a href=players.php?pid=62678&edition=5>GClothier</a></td>
        <td>1</td>
        <td>9868.960</td>
        <td>172.000</td>
    </tr>
    <tr>
        <td>1951</td>
        <td><a href=players.php?pid=34583&edition=5>Kazuull</a></td>
        <td>1</td>
        <td>9868.960</td>
        <td>172.000</td>
    </tr>
    <tr>
        <td>1952</td>
        <td><a href=players.php?pid=18342&edition=5>Shinmah</a></td>
        <td>1</td>
        <td>9869.000</td>
        <td>175.000</td>
    </tr>
    <tr>
        <td>1953</td>
        <td><a href=players.php?pid=66097&edition=5>SAVAGE_SKULL001</a></td>
        <td>1</td>
        <td>9869.000</td>
        <td>175.000</td>
    </tr>
    <tr>
        <td>1954</td>
        <td><a href=players.php?pid=71329&edition=5>japabtw.</a></td>
        <td>1</td>
        <td>9869.027</td>
        <td>177.000</td>
    </tr>
    <tr>
        <td>1955</td>
        <td><a href=players.php?pid=37041&edition=5>Jhonz0r</a></td>
        <td>1</td>
        <td>9869.067</td>
        <td>180.000</td>
    </tr>
    <tr>
        <td>1956</td>
        <td><a href=players.php?pid=72021&edition=5>HoneyDumplinn</a></td>
        <td>1</td>
        <td>9869.160</td>
        <td>187.000</td>
    </tr>
    <tr>
        <td>1957</td>
        <td><a href=players.php?pid=62858&edition=5>Rakkenx</a></td>
        <td>1</td>
        <td>9869.173</td>
        <td>188.000</td>
    </tr>
    <tr>
        <td>1958</td>
        <td><a href=players.php?pid=68522&edition=5>Saurianfi</a></td>
        <td>1</td>
        <td>9869.227</td>
        <td>192.000</td>
    </tr>
    <tr>
        <td>1959</td>
        <td><a href=players.php?pid=61096&edition=5>grfa.</a></td>
        <td>1</td>
        <td>9869.227</td>
        <td>192.000</td>
    </tr>
    <tr>
        <td>1960</td>
        <td><a href=players.php?pid=9370&edition=5>IArtoI</a></td>
        <td>1</td>
        <td>9869.240</td>
        <td>193.000</td>
    </tr>
    <tr>
        <td>1961</td>
        <td><a href=players.php?pid=68377&edition=5>kylegp14</a></td>
        <td>1</td>
        <td>9869.240</td>
        <td>193.000</td>
    </tr>
    <tr>
        <td>1962</td>
        <td><a href=players.php?pid=60308&edition=5>TheSeriousDark</a></td>
        <td>1</td>
        <td>9869.267</td>
        <td>195.000</td>
    </tr>
    <tr>
        <td>1963</td>
        <td><a href=players.php?pid=8725&edition=5>Jingsterlinger</a></td>
        <td>1</td>
        <td>9869.280</td>
        <td>196.000</td>
    </tr>
    <tr>
        <td>1964</td>
        <td><a href=players.php?pid=35944&edition=5>Knugg8</a></td>
        <td>1</td>
        <td>9869.280</td>
        <td>196.000</td>
    </tr>
    <tr>
        <td>1965</td>
        <td><a href=players.php?pid=67961&edition=5>lMcGoose</a></td>
        <td>1</td>
        <td>9869.293</td>
        <td>197.000</td>
    </tr>
    <tr>
        <td>1966</td>
        <td><a href=players.php?pid=47656&edition=5>palito_TM</a></td>
        <td>1</td>
        <td>9869.320</td>
        <td>199.000</td>
    </tr>
    <tr>
        <td>1967</td>
        <td><a href=players.php?pid=644&edition=5>Imm0rtalSamurai</a></td>
        <td>1</td>
        <td>9869.333</td>
        <td>200.000</td>
    </tr>
    <tr>
        <td>1968</td>
        <td><a href=players.php?pid=50381&edition=5>Bwaakchicken123</a></td>
        <td>1</td>
        <td>9869.360</td>
        <td>202.000</td>
    </tr>
    <tr>
        <td>1969</td>
        <td><a href=players.php?pid=64530&edition=5><span style='color:#11aaff;'>b</span><span
                    style='color:#66aaee;'>e</span><span style='color:#aaaadd;'>n</span><span
                    style='color:#ffbbbb;'>j</span><span style='color:#ffbbbb;'>i</span><span
                    style='color:#ffccdd;'>P</span><span style='color:#ffeeee;'>K</span><span
                    style='color:#ffffff;'>S</span></a></td>
        <td>1</td>
        <td>9869.360</td>
        <td>202.000</td>
    </tr>
    <tr>
        <td>1970</td>
        <td><a href=players.php?pid=53386&edition=5>MrAlease</a></td>
        <td>1</td>
        <td>9869.373</td>
        <td>203.000</td>
    </tr>
    <tr>
        <td>1971</td>
        <td><a href=players.php?pid=37707&edition=5>Lewzo</a></td>
        <td>1</td>
        <td>9869.387</td>
        <td>204.000</td>
    </tr>
    <tr>
        <td>1972</td>
        <td><a href=players.php?pid=67420&edition=5>duh.duh</a></td>
        <td>1</td>
        <td>9869.480</td>
        <td>211.000</td>
    </tr>
    <tr>
        <td>1973</td>
        <td><a href=players.php?pid=52157&edition=5>Drakon_sp</a></td>
        <td>1</td>
        <td>9869.480</td>
        <td>211.000</td>
    </tr>
    <tr>
        <td>1974</td>
        <td><a href=players.php?pid=67770&edition=5>Mael60</a></td>
        <td>1</td>
        <td>9869.493</td>
        <td>212.000</td>
    </tr>
    <tr>
        <td>1975</td>
        <td><a href=players.php?pid=69606&edition=5>Lutze__</a></td>
        <td>1</td>
        <td>9869.507</td>
        <td>213.000</td>
    </tr>
    <tr>
        <td>1976</td>
        <td><a href=players.php?pid=58258&edition=5>Crispr_OW</a></td>
        <td>1</td>
        <td>9869.507</td>
        <td>213.000</td>
    </tr>
    <tr>
        <td>1977</td>
        <td><a href=players.php?pid=70758&edition=5>UserNotFound72</a></td>
        <td>1</td>
        <td>9869.520</td>
        <td>214.000</td>
    </tr>
    <tr>
        <td>1978</td>
        <td><a href=players.php?pid=65318&edition=5>RubenT</a></td>
        <td>1</td>
        <td>9869.533</td>
        <td>215.000</td>
    </tr>
    <tr>
        <td>1979</td>
        <td><a href=players.php?pid=5181&edition=5>Fer0xSR</a></td>
        <td>1</td>
        <td>9869.547</td>
        <td>216.000</td>
    </tr>
    <tr>
        <td>1980</td>
        <td><a href=players.php?pid=50845&edition=5><span style='color:#990099;'>&nbsp;dae</span></a></td>
        <td>1</td>
        <td>9869.547</td>
        <td>216.000</td>
    </tr>
    <tr>
        <td>1981</td>
        <td><a href=players.php?pid=2933&edition=5>hefest</a></td>
        <td>1</td>
        <td>9869.560</td>
        <td>217.000</td>
    </tr>
    <tr>
        <td>1982</td>
        <td><a href=players.php?pid=66223&edition=5>vku1023</a></td>
        <td>1</td>
        <td>9869.587</td>
        <td>219.000</td>
    </tr>
    <tr>
        <td>1983</td>
        <td><a href=players.php?pid=70105&edition=5>eiylia</a></td>
        <td>1</td>
        <td>9869.600</td>
        <td>220.000</td>
    </tr>
    <tr>
        <td>1984</td>
        <td><a href=players.php?pid=60545&edition=5>the_Soba</a></td>
        <td>1</td>
        <td>9869.613</td>
        <td>221.000</td>
    </tr>
    <tr>
        <td>1985</td>
        <td><a href=players.php?pid=31681&edition=5>Trumps&nbsp;Middle&nbsp;Nut</a></td>
        <td>1</td>
        <td>9869.627</td>
        <td>222.000</td>
    </tr>
    <tr>
        <td>1986</td>
        <td><a href=players.php?pid=69210&edition=5>hflott</a></td>
        <td>1</td>
        <td>9869.627</td>
        <td>222.000</td>
    </tr>
    <tr>
        <td>1987</td>
        <td><a href=players.php?pid=6886&edition=5>Areia25</a></td>
        <td>1</td>
        <td>9869.640</td>
        <td>223.000</td>
    </tr>
    <tr>
        <td>1988</td>
        <td><a href=players.php?pid=6840&edition=5><span style='color:#ff33cc;'>p</span><span
                    style='color:#ff66cc;'>i</span><span style='color:#ff6699;'>t</span><span
                    style='color:#ff99cc;'>o</span><span style='color:#ff6699;'>u</span><span
                    style='color:#ff66cc;'>n</span><span style='color:#ff33cc;'>e</span></a></td>
        <td>1</td>
        <td>9869.653</td>
        <td>224.000</td>
    </tr>
    <tr>
        <td>1989</td>
        <td><a href=players.php?pid=36398&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Yvory</span></a></td>
        <td>1</td>
        <td>9869.680</td>
        <td>226.000</td>
    </tr>
    <tr>
        <td>1990</td>
        <td><a href=players.php?pid=35833&edition=5>SodDanut</a></td>
        <td>1</td>
        <td>9869.680</td>
        <td>226.000</td>
    </tr>
    <tr>
        <td>1991</td>
        <td><a href=players.php?pid=57530&edition=5>Thekirisaki</a></td>
        <td>1</td>
        <td>9869.720</td>
        <td>229.000</td>
    </tr>
    <tr>
        <td>1992</td>
        <td><a href=players.php?pid=67461&edition=5>trackstar525</a></td>
        <td>1</td>
        <td>9869.760</td>
        <td>232.000</td>
    </tr>
    <tr>
        <td>1993</td>
        <td><a href=players.php?pid=30016&edition=5><span style='color:#bb0044;font-weight:bold;'>S</span><span
                    style='color:#990066;font-weight:bold;'>a</span><span
                    style='color:#770088;font-weight:bold;'>r</span><span
                    style='color:#5500aa;font-weight:bold;'>i</span><span
                    style='color:#3300cc;font-weight:bold;'>n</span><span
                    style='color:#1100ee;font-weight:bold;'>d</span></a></td>
        <td>1</td>
        <td>9869.773</td>
        <td>233.000</td>
    </tr>
    <tr>
        <td>1994</td>
        <td><a href=players.php?pid=63179&edition=5>BryanShelv</a></td>
        <td>1</td>
        <td>9869.787</td>
        <td>234.000</td>
    </tr>
    <tr>
        <td>1995</td>
        <td><a href=players.php?pid=43323&edition=5>Kittov3</a></td>
        <td>1</td>
        <td>9869.787</td>
        <td>234.000</td>
    </tr>
    <tr>
        <td>1996</td>
        <td><a href=players.php?pid=57972&edition=5>KrudeTM</a></td>
        <td>1</td>
        <td>9869.800</td>
        <td>235.000</td>
    </tr>
    <tr>
        <td>1997</td>
        <td><a href=players.php?pid=70903&edition=5>KennBey</a></td>
        <td>1</td>
        <td>9869.813</td>
        <td>236.000</td>
    </tr>
    <tr>
        <td>1998</td>
        <td><a href=players.php?pid=70129&edition=5>Matihere</a></td>
        <td>1</td>
        <td>9869.827</td>
        <td>237.000</td>
    </tr>
    <tr>
        <td>1999</td>
        <td><a href=players.php?pid=37271&edition=5><span style='color:#55ee11;'>&Scaron;</span><span
                    style='color:#aa11cc;'>Ē</span><span style='color:#aa11cc;'>m</span><span
                    style='color:#ee2222;'>Ĕ</span><span style='color:#000000;'>Ň&macr;</span><span
                    style='color:#000000;font-style:italic;letter-spacing: -0.1em;font-size:smaller'>ĎĔmŎŇ</span></a>
        </td>
        <td>1</td>
        <td>9869.840</td>
        <td>238.000</td>
    </tr>
    <tr>
        <td>2000</td>
        <td><a href=players.php?pid=17945&edition=5>LikeAFaultier</a></td>
        <td>1</td>
        <td>9869.840</td>
        <td>238.000</td>
    </tr>
    <tr>
        <td>2001</td>
        <td><a href=players.php?pid=72777&edition=5>bard_117</a></td>
        <td>1</td>
        <td>9869.840</td>
        <td>238.000</td>
    </tr>
    <tr>
        <td>2002</td>
        <td><a href=players.php?pid=54112&edition=5>Tim888881</a></td>
        <td>1</td>
        <td>9869.867</td>
        <td>240.000</td>
    </tr>
    <tr>
        <td>2003</td>
        <td><a href=players.php?pid=69435&edition=5>mult1s8m</a></td>
        <td>1</td>
        <td>9869.893</td>
        <td>242.000</td>
    </tr>
    <tr>
        <td>2004</td>
        <td><a href=players.php?pid=32112&edition=5><span style='color:#553377;'>Jato</span><span
                    style='color:#663388;'>TM</span></a></td>
        <td>1</td>
        <td>9869.907</td>
        <td>243.000</td>
    </tr>
    <tr>
        <td>2005</td>
        <td><a href=players.php?pid=50400&edition=5>Tolikz_R</a></td>
        <td>1</td>
        <td>9869.907</td>
        <td>243.000</td>
    </tr>
    <tr>
        <td>2006</td>
        <td><a href=players.php?pid=69697&edition=5>JoesMama21</a></td>
        <td>1</td>
        <td>9869.907</td>
        <td>243.000</td>
    </tr>
    <tr>
        <td>2007</td>
        <td><a href=players.php?pid=70068&edition=5>oko_cha</a></td>
        <td>1</td>
        <td>9869.920</td>
        <td>244.000</td>
    </tr>
    <tr>
        <td>2008</td>
        <td><a href=players.php?pid=50142&edition=5>tonication</a></td>
        <td>1</td>
        <td>9869.960</td>
        <td>247.000</td>
    </tr>
    <tr>
        <td>2009</td>
        <td><a href=players.php?pid=68465&edition=5><span style='color:#8800ff;'>ル</span><span
                    style='color:#dd00ff;'>ー</span><span style='color:#ff00ff;'>ビ</span><span
                    style='color:#ff0077;'>ン</span></a></td>
        <td>1</td>
        <td>9870.013</td>
        <td>251.000</td>
    </tr>
    <tr>
        <td>2010</td>
        <td><a href=players.php?pid=33705&edition=5>druduche</a></td>
        <td>1</td>
        <td>9870.027</td>
        <td>252.000</td>
    </tr>
    <tr>
        <td>2011</td>
        <td><a href=players.php?pid=66572&edition=5>EnigmaPePe</a></td>
        <td>1</td>
        <td>9870.040</td>
        <td>253.000</td>
    </tr>
    <tr>
        <td>2012</td>
        <td><a href=players.php?pid=70078&edition=5>slphrrr</a></td>
        <td>1</td>
        <td>9870.053</td>
        <td>254.000</td>
    </tr>
    <tr>
        <td>2013</td>
        <td><a href=players.php?pid=62900&edition=5>pepdead</a></td>
        <td>1</td>
        <td>9870.080</td>
        <td>256.000</td>
    </tr>
    <tr>
        <td>2014</td>
        <td><a href=players.php?pid=29049&edition=5>Herolity_Bount7</a></td>
        <td>1</td>
        <td>9870.080</td>
        <td>256.000</td>
    </tr>
    <tr>
        <td>2015</td>
        <td><a href=players.php?pid=69740&edition=5>RandomInsight1</a></td>
        <td>1</td>
        <td>9870.080</td>
        <td>256.000</td>
    </tr>
    <tr>
        <td>2016</td>
        <td><a href=players.php?pid=3070&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Lukagi</span></a></td>
        <td>1</td>
        <td>9870.147</td>
        <td>261.000</td>
    </tr>
    <tr>
        <td>2017</td>
        <td><a href=players.php?pid=17480&edition=5>Squadere</a></td>
        <td>1</td>
        <td>9870.227</td>
        <td>267.000</td>
    </tr>
    <tr>
        <td>2018</td>
        <td><a href=players.php?pid=54534&edition=5>taituy</a></td>
        <td>1</td>
        <td>9870.227</td>
        <td>267.000</td>
    </tr>
    <tr>
        <td>2019</td>
        <td><a href=players.php?pid=23555&edition=5><span style='color:#009933;'>He</span><span
                    style='color:#009944;'>isen</span><span style='color:#009955;'>burg</span><span
                    style='color:#009966;'>er</span></a></td>
        <td>1</td>
        <td>9870.240</td>
        <td>268.000</td>
    </tr>
    <tr>
        <td>2020</td>
        <td><a href=players.php?pid=32399&edition=5>NikoRuffet</a></td>
        <td>1</td>
        <td>9870.253</td>
        <td>269.000</td>
    </tr>
    <tr>
        <td>2021</td>
        <td><a href=players.php?pid=71330&edition=5>NotJoshiTM</a></td>
        <td>1</td>
        <td>9870.253</td>
        <td>269.000</td>
    </tr>
    <tr>
        <td>2022</td>
        <td><a href=players.php?pid=29771&edition=5><span style='color:#bbccdd;'>S</span><span
                    style='color:#ccbbaa;'>&Lambda;</span><span style='color:#ddaa77;'>&Lambda;</span><span
                    style='color:#ee9933;'>Ϗ</span><span style='color:#ff8800;'>&beta;</span></a></td>
        <td>1</td>
        <td>9870.293</td>
        <td>272.000</td>
    </tr>
    <tr>
        <td>2023</td>
        <td><a href=players.php?pid=8850&edition=5>JacobGames66</a></td>
        <td>1</td>
        <td>9870.320</td>
        <td>274.000</td>
    </tr>
    <tr>
        <td>2024</td>
        <td><a href=players.php?pid=56921&edition=5>Memam_6</a></td>
        <td>1</td>
        <td>9870.347</td>
        <td>276.000</td>
    </tr>
    <tr>
        <td>2025</td>
        <td><a href=players.php?pid=67712&edition=5>Tawinner</a></td>
        <td>1</td>
        <td>9870.373</td>
        <td>278.000</td>
    </tr>
    <tr>
        <td>2026</td>
        <td><a href=players.php?pid=10789&edition=5>W0osah</a></td>
        <td>1</td>
        <td>9870.387</td>
        <td>279.000</td>
    </tr>
    <tr>
        <td>2027</td>
        <td><a href=players.php?pid=5915&edition=5><span style='color:#00ff77;'>Speedself</span></a></td>
        <td>1</td>
        <td>9870.387</td>
        <td>279.000</td>
    </tr>
    <tr>
        <td>2028</td>
        <td><a href=players.php?pid=55508&edition=5>mat01f</a></td>
        <td>1</td>
        <td>9870.413</td>
        <td>281.000</td>
    </tr>
    <tr>
        <td>2029</td>
        <td><a href=players.php?pid=67434&edition=5>Robin_Hood529</a></td>
        <td>1</td>
        <td>9870.427</td>
        <td>282.000</td>
    </tr>
    <tr>
        <td>2030</td>
        <td><a href=players.php?pid=44607&edition=5>Mamma_mia_Menno</a></td>
        <td>1</td>
        <td>9870.427</td>
        <td>282.000</td>
    </tr>
    <tr>
        <td>2031</td>
        <td><a href=players.php?pid=68170&edition=5>p00gler</a></td>
        <td>1</td>
        <td>9870.467</td>
        <td>285.000</td>
    </tr>
    <tr>
        <td>2032</td>
        <td><a href=players.php?pid=31074&edition=5>Bobbzila</a></td>
        <td>1</td>
        <td>9870.547</td>
        <td>291.000</td>
    </tr>
    <tr>
        <td>2033</td>
        <td><a href=players.php?pid=31294&edition=5><span style='color:#ffbb00;'>A</span><span
                    style='color:#eebb00;'>y</span><span style='color:#ccaa11;'>r</span><span
                    style='color:#bbaa11;'>t</span><span style='color:#aaaa11;'>o</span><span
                    style='color:#99aa22;'>n</span><span style='color:#779922;'>&nbsp;</span><span
                    style='color:#669922;'>S</span><span style='color:#559922;'>e</span><span
                    style='color:#338833;'>n</span><span style='color:#228833;'>n</span><span
                    style='color:#228833;'>a</span><span style='color:#227733;'>&nbsp;</span><span
                    style='color:#226633;'>d</span><span style='color:#115544;'>a</span><span
                    style='color:#114444;'>&nbsp;S</span><span style='color:#113344;'>i</span><span
                    style='color:#002255;'>l</span><span style='color:#001155;'>v</span><span
                    style='color:#000055;'>&aacute;</span></a></td>
        <td>1</td>
        <td>9870.547</td>
        <td>291.000</td>
    </tr>
    <tr>
        <td>2034</td>
        <td><a href=players.php?pid=66933&edition=5>plaah13</a></td>
        <td>1</td>
        <td>9870.573</td>
        <td>293.000</td>
    </tr>
    <tr>
        <td>2035</td>
        <td><a href=players.php?pid=69108&edition=5>LPinkShoesL</a></td>
        <td>1</td>
        <td>9870.573</td>
        <td>293.000</td>
    </tr>
    <tr>
        <td>2036</td>
        <td><a href=players.php?pid=70582&edition=5>TTV.5ea7ay</a></td>
        <td>1</td>
        <td>9870.627</td>
        <td>297.000</td>
    </tr>
    <tr>
        <td>2037</td>
        <td><a href=players.php?pid=571&edition=5>weppex</a></td>
        <td>1</td>
        <td>9870.707</td>
        <td>303.000</td>
    </tr>
    <tr>
        <td>2038</td>
        <td><a href=players.php?pid=12514&edition=5>AssoCiap</a></td>
        <td>1</td>
        <td>9870.720</td>
        <td>304.000</td>
    </tr>
    <tr>
        <td>2039</td>
        <td><a href=players.php?pid=46219&edition=5>Luxke013</a></td>
        <td>1</td>
        <td>9870.720</td>
        <td>304.000</td>
    </tr>
    <tr>
        <td>2040</td>
        <td><a href=players.php?pid=68074&edition=5>TOnyrino</a></td>
        <td>1</td>
        <td>9870.747</td>
        <td>306.000</td>
    </tr>
    <tr>
        <td>2041</td>
        <td><a href=players.php?pid=67178&edition=5>HoorayCosine390</a></td>
        <td>1</td>
        <td>9870.773</td>
        <td>308.000</td>
    </tr>
    <tr>
        <td>2042</td>
        <td><a href=players.php?pid=45535&edition=5><span style='color:#9999ff;'>a</span><span
                    style='color:#9988ff;'>b</span><span style='color:#8888ff;'>i</span><span
                    style='color:#8877ee;'>g</span><span style='color:#7766ee;'>f</span><span
                    style='color:#7755ee;'>a</span><span style='color:#6655ee;'>t</span><span
                    style='color:#6644dd;'>p</span><span style='color:#5533dd;'>o</span><span
                    style='color:#5522dd;'>t</span><span style='color:#4422dd;'>a</span><span
                    style='color:#4411cc;'>t</span><span style='color:#3300cc;'>o</span></a></td>
        <td>1</td>
        <td>9870.800</td>
        <td>310.000</td>
    </tr>
    <tr>
        <td>2043</td>
        <td><a href=players.php?pid=49704&edition=5>Enphydeon</a></td>
        <td>1</td>
        <td>9870.800</td>
        <td>310.000</td>
    </tr>
    <tr>
        <td>2044</td>
        <td><a href=players.php?pid=52778&edition=5>MouseWithBeer</a></td>
        <td>1</td>
        <td>9870.867</td>
        <td>315.000</td>
    </tr>
    <tr>
        <td>2045</td>
        <td><a href=players.php?pid=12836&edition=5>Mastack2</a></td>
        <td>1</td>
        <td>9870.880</td>
        <td>316.000</td>
    </tr>
    <tr>
        <td>2046</td>
        <td><a href=players.php?pid=69068&edition=5>Choyvv</a></td>
        <td>1</td>
        <td>9870.893</td>
        <td>317.000</td>
    </tr>
    <tr>
        <td>2047</td>
        <td><a href=players.php?pid=43988&edition=5>Mangodancer</a></td>
        <td>1</td>
        <td>9870.893</td>
        <td>317.000</td>
    </tr>
    <tr>
        <td>2048</td>
        <td><a href=players.php?pid=65897&edition=5>Okazakikunnn</a></td>
        <td>1</td>
        <td>9870.907</td>
        <td>318.000</td>
    </tr>
    <tr>
        <td>2049</td>
        <td><a href=players.php?pid=7265&edition=5>Suke.4PF</a></td>
        <td>1</td>
        <td>9870.907</td>
        <td>318.000</td>
    </tr>
    <tr>
        <td>2050</td>
        <td><a href=players.php?pid=46581&edition=5><span style='color:#9900cc;'>G</span><span
                    style='color:#bb00dd;'>a</span><span style='color:#dd00ee;'>s</span><span
                    style='color:#ff00ff;'>t</span><span style='color:#ff00ff;'>h</span><span
                    style='color:#cc00ee;'>u</span><span style='color:#9900cc;'>g</span></a></td>
        <td>1</td>
        <td>9870.907</td>
        <td>318.000</td>
    </tr>
    <tr>
        <td>2051</td>
        <td><a href=players.php?pid=71731&edition=5>pxlmike</a></td>
        <td>1</td>
        <td>9870.920</td>
        <td>319.000</td>
    </tr>
    <tr>
        <td>2052</td>
        <td><a href=players.php?pid=69450&edition=5>whymee99</a></td>
        <td>1</td>
        <td>9870.947</td>
        <td>321.000</td>
    </tr>
    <tr>
        <td>2053</td>
        <td><a href=players.php?pid=68337&edition=5>Krios_Ples_</a></td>
        <td>1</td>
        <td>9870.960</td>
        <td>322.000</td>
    </tr>
    <tr>
        <td>2054</td>
        <td><a href=players.php?pid=32073&edition=5>EnzoRNN</a></td>
        <td>1</td>
        <td>9870.973</td>
        <td>323.000</td>
    </tr>
    <tr>
        <td>2055</td>
        <td><a href=players.php?pid=64364&edition=5>theotherguy1356</a></td>
        <td>1</td>
        <td>9870.987</td>
        <td>324.000</td>
    </tr>
    <tr>
        <td>2056</td>
        <td><a href=players.php?pid=31799&edition=5>MINECRUSHER14</a></td>
        <td>1</td>
        <td>9871.000</td>
        <td>325.000</td>
    </tr>
    <tr>
        <td>2057</td>
        <td><a href=players.php?pid=69080&edition=5>Dirt.Road</a></td>
        <td>1</td>
        <td>9871.000</td>
        <td>325.000</td>
    </tr>
    <tr>
        <td>2058</td>
        <td><a href=players.php?pid=47427&edition=5>levellogs2</a></td>
        <td>1</td>
        <td>9871.027</td>
        <td>327.000</td>
    </tr>
    <tr>
        <td>2059</td>
        <td><a href=players.php?pid=22497&edition=5>maybevenox</a></td>
        <td>1</td>
        <td>9871.040</td>
        <td>328.000</td>
    </tr>
    <tr>
        <td>2060</td>
        <td><a href=players.php?pid=43927&edition=5>iknacx</a></td>
        <td>1</td>
        <td>9871.040</td>
        <td>328.000</td>
    </tr>
    <tr>
        <td>2061</td>
        <td><a href=players.php?pid=5680&edition=5><span style='color:#00ccff;'>C</span><span
                    style='color:#22bbff;'>1</span><span style='color:#3399ff;'>F</span><span
                    style='color:#3399ff;'>3</span><span style='color:#00ccff;'>R</span></a></td>
        <td>1</td>
        <td>9871.053</td>
        <td>329.000</td>
    </tr>
    <tr>
        <td>2062</td>
        <td><a href=players.php?pid=66566&edition=5>LuLOooKIIING</a></td>
        <td>1</td>
        <td>9871.067</td>
        <td>330.000</td>
    </tr>
    <tr>
        <td>2063</td>
        <td><a href=players.php?pid=39266&edition=5>Daboys9252</a></td>
        <td>1</td>
        <td>9871.080</td>
        <td>331.000</td>
    </tr>
    <tr>
        <td>2064</td>
        <td><a href=players.php?pid=69024&edition=5>philipfunny</a></td>
        <td>1</td>
        <td>9871.093</td>
        <td>332.000</td>
    </tr>
    <tr>
        <td>2065</td>
        <td><a href=players.php?pid=67016&edition=5><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>[</span><span
                    style='color:#ff8800;letter-spacing: -0.1em;font-size:smaller'>BTC</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>]&nbsp;</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>Ϻatt</span><span
                    style='color:#ff8800;letter-spacing: -0.1em;font-size:smaller'>'</span><span
                    style='color:#000000;letter-spacing: -0.1em;font-size:smaller'>s&nbsp;</span><span
                    style='color:#ff8800;letter-spacing: -0.1em;font-size:smaller'>Sats</span></a></td>
        <td>1</td>
        <td>9871.120</td>
        <td>334.000</td>
    </tr>
    <tr>
        <td>2066</td>
        <td><a href=players.php?pid=30318&edition=5>matidfk</a></td>
        <td>1</td>
        <td>9871.133</td>
        <td>335.000</td>
    </tr>
    <tr>
        <td>2067</td>
        <td><a href=players.php?pid=32114&edition=5><span style='color:#33cccc;'>T</span><span
                    style='color:#77aaaa;'>o</span><span style='color:#bb9999;'>m</span><span
                    style='color:#ff7777;'>i</span></a></td>
        <td>1</td>
        <td>9871.147</td>
        <td>336.000</td>
    </tr>
    <tr>
        <td>2068</td>
        <td><a href=players.php?pid=66966&edition=5>Bamb0o</a></td>
        <td>1</td>
        <td>9871.160</td>
        <td>337.000</td>
    </tr>
    <tr>
        <td>2069</td>
        <td><a href=players.php?pid=19276&edition=5>Sjezusmina</a></td>
        <td>1</td>
        <td>9871.160</td>
        <td>337.000</td>
    </tr>
    <tr>
        <td>2070</td>
        <td><a href=players.php?pid=1953&edition=5>PietonTM</a></td>
        <td>1</td>
        <td>9871.187</td>
        <td>339.000</td>
    </tr>
    <tr>
        <td>2071</td>
        <td><a href=players.php?pid=47807&edition=5>ohiorizz</a></td>
        <td>1</td>
        <td>9871.240</td>
        <td>343.000</td>
    </tr>
    <tr>
        <td>2072</td>
        <td><a href=players.php?pid=10252&edition=5>Qiraj_TM</a></td>
        <td>1</td>
        <td>9871.253</td>
        <td>344.000</td>
    </tr>
    <tr>
        <td>2073</td>
        <td><a href=players.php?pid=68193&edition=5>henke121</a></td>
        <td>1</td>
        <td>9871.253</td>
        <td>344.000</td>
    </tr>
    <tr>
        <td>2074</td>
        <td><a href=players.php?pid=67111&edition=5>Kianastar</a></td>
        <td>1</td>
        <td>9871.267</td>
        <td>345.000</td>
    </tr>
    <tr>
        <td>2075</td>
        <td><a href=players.php?pid=68462&edition=5><span style='color:#99ff66;'>c</span><span
                    style='color:#88dd88;'>h</span><span style='color:#66bbbb;'>e</span><span
                    style='color:#5588dd;'>r</span><span style='color:#3366ff;'>r</span><span
                    style='color:#3366ff;'>y</span><span style='color:#3344ff;'>2</span><span
                    style='color:#3322ff;'>_</span>0</a></td>
        <td>1</td>
        <td>9871.280</td>
        <td>346.000</td>
    </tr>
    <tr>
        <td>2076</td>
        <td><a href=players.php?pid=1442&edition=5>Drayn_06</a></td>
        <td>1</td>
        <td>9871.293</td>
        <td>347.000</td>
    </tr>
    <tr>
        <td>2077</td>
        <td><a href=players.php?pid=51778&edition=5>TelegraphGo</a></td>
        <td>1</td>
        <td>9871.347</td>
        <td>351.000</td>
    </tr>
    <tr>
        <td>2078</td>
        <td><a href=players.php?pid=34424&edition=5>RedW1z</a></td>
        <td>1</td>
        <td>9871.373</td>
        <td>353.000</td>
    </tr>
    <tr>
        <td>2079</td>
        <td><a href=players.php?pid=67409&edition=5>orzelek_</a></td>
        <td>1</td>
        <td>9871.387</td>
        <td>354.000</td>
    </tr>
    <tr>
        <td>2080</td>
        <td><a href=players.php?pid=2288&edition=5>manamiz</a></td>
        <td>1</td>
        <td>9871.387</td>
        <td>354.000</td>
    </tr>
    <tr>
        <td>2081</td>
        <td><a href=players.php?pid=43423&edition=5>Draconic_Sword</a></td>
        <td>1</td>
        <td>9871.400</td>
        <td>355.000</td>
    </tr>
    <tr>
        <td>2082</td>
        <td><a href=players.php?pid=67304&edition=5>Dannyboi33</a></td>
        <td>1</td>
        <td>9871.413</td>
        <td>356.000</td>
    </tr>
    <tr>
        <td>2083</td>
        <td><a href=players.php?pid=55193&edition=5>Blue_GT999</a></td>
        <td>1</td>
        <td>9871.413</td>
        <td>356.000</td>
    </tr>
    <tr>
        <td>2084</td>
        <td><a href=players.php?pid=39465&edition=5>dofpop</a></td>
        <td>1</td>
        <td>9871.440</td>
        <td>358.000</td>
    </tr>
    <tr>
        <td>2085</td>
        <td><a href=players.php?pid=12394&edition=5>hey_bb</a></td>
        <td>1</td>
        <td>9871.480</td>
        <td>361.000</td>
    </tr>
    <tr>
        <td>2086</td>
        <td><a href=players.php?pid=71034&edition=5>Gwilfox</a></td>
        <td>1</td>
        <td>9871.480</td>
        <td>361.000</td>
    </tr>
    <tr>
        <td>2087</td>
        <td><a href=players.php?pid=55446&edition=5>stanneman99</a></td>
        <td>1</td>
        <td>9871.480</td>
        <td>361.000</td>
    </tr>
    <tr>
        <td>2088</td>
        <td><a href=players.php?pid=69879&edition=5>Mozcart_</a></td>
        <td>1</td>
        <td>9871.493</td>
        <td>362.000</td>
    </tr>
    <tr>
        <td>2089</td>
        <td><a href=players.php?pid=2464&edition=5>JajaTM</a></td>
        <td>1</td>
        <td>9871.493</td>
        <td>362.000</td>
    </tr>
    <tr>
        <td>2090</td>
        <td><a href=players.php?pid=56005&edition=5>LovelaceLIVE</a></td>
        <td>1</td>
        <td>9871.493</td>
        <td>362.000</td>
    </tr>
    <tr>
        <td>2091</td>
        <td><a href=players.php?pid=48758&edition=5>BigBoiBagginz</a></td>
        <td>1</td>
        <td>9871.520</td>
        <td>364.000</td>
    </tr>
    <tr>
        <td>2092</td>
        <td><a href=players.php?pid=21029&edition=5>TCxConcept</a></td>
        <td>1</td>
        <td>9871.533</td>
        <td>365.000</td>
    </tr>
    <tr>
        <td>2093</td>
        <td><a href=players.php?pid=68654&edition=5>Galenpanda</a></td>
        <td>1</td>
        <td>9871.547</td>
        <td>366.000</td>
    </tr>
    <tr>
        <td>2094</td>
        <td><a href=players.php?pid=21350&edition=5>Sakura-Neko_</a></td>
        <td>1</td>
        <td>9871.573</td>
        <td>368.000</td>
    </tr>
    <tr>
        <td>2095</td>
        <td><a href=players.php?pid=68312&edition=5>minky_stinky</a></td>
        <td>1</td>
        <td>9871.587</td>
        <td>369.000</td>
    </tr>
    <tr>
        <td>2096</td>
        <td><a href=players.php?pid=56385&edition=5>Mertzert</a></td>
        <td>1</td>
        <td>9871.613</td>
        <td>371.000</td>
    </tr>
    <tr>
        <td>2097</td>
        <td><a href=players.php?pid=28969&edition=5>GhiMax</a></td>
        <td>1</td>
        <td>9871.653</td>
        <td>374.000</td>
    </tr>
    <tr>
        <td>2098</td>
        <td><a href=players.php?pid=71447&edition=5>HyperenorTM</a></td>
        <td>1</td>
        <td>9871.707</td>
        <td>378.000</td>
    </tr>
    <tr>
        <td>2099</td>
        <td><a href=players.php?pid=72642&edition=5>Liiferuiner</a></td>
        <td>1</td>
        <td>9871.747</td>
        <td>381.000</td>
    </tr>
    <tr>
        <td>2100</td>
        <td><a href=players.php?pid=33161&edition=5>Inferno_2424</a></td>
        <td>1</td>
        <td>9871.760</td>
        <td>382.000</td>
    </tr>
    <tr>
        <td>2101</td>
        <td><a href=players.php?pid=70770&edition=5>TTVJakeCH</a></td>
        <td>1</td>
        <td>9871.773</td>
        <td>383.000</td>
    </tr>
    <tr>
        <td>2102</td>
        <td><a href=players.php?pid=67399&edition=5>Sekuu.g4</a></td>
        <td>1</td>
        <td>9871.787</td>
        <td>384.000</td>
    </tr>
    <tr>
        <td>2103</td>
        <td><a href=players.php?pid=68015&edition=5>SuperFriendMan</a></td>
        <td>1</td>
        <td>9871.800</td>
        <td>385.000</td>
    </tr>
    <tr>
        <td>2104</td>
        <td><a href=players.php?pid=53271&edition=5>Mr__HH</a></td>
        <td>1</td>
        <td>9871.813</td>
        <td>386.000</td>
    </tr>
    <tr>
        <td>2105</td>
        <td><a href=players.php?pid=61781&edition=5>CreamyTM</a></td>
        <td>1</td>
        <td>9871.813</td>
        <td>386.000</td>
    </tr>
    <tr>
        <td>2106</td>
        <td><a href=players.php?pid=65438&edition=5>QuadRadicalTM</a></td>
        <td>1</td>
        <td>9871.840</td>
        <td>388.000</td>
    </tr>
    <tr>
        <td>2107</td>
        <td><a href=players.php?pid=69493&edition=5>Voxlez</a></td>
        <td>1</td>
        <td>9871.840</td>
        <td>388.000</td>
    </tr>
    <tr>
        <td>2108</td>
        <td><a href=players.php?pid=351&edition=5><span style='color:#ff0000;'>S</span><span
                    style='color:#ff3300;'>o</span><span style='color:#ff5500;'>g</span><span
                    style='color:#ff8800;'>g</span><span style='color:#ffaa00;'>e</span><span
                    style='color:#ffdd00;'>9</span><span style='color:#ffff00;'>3&nbsp;:peepohappy:</span></a></td>
        <td>1</td>
        <td>9871.840</td>
        <td>388.000</td>
    </tr>
    <tr>
        <td>2109</td>
        <td><a href=players.php?pid=33745&edition=5>Xancius</a></td>
        <td>1</td>
        <td>9871.867</td>
        <td>390.000</td>
    </tr>
    <tr>
        <td>2110</td>
        <td><a href=players.php?pid=51218&edition=5>Rekcuting</a></td>
        <td>1</td>
        <td>9871.867</td>
        <td>390.000</td>
    </tr>
    <tr>
        <td>2111</td>
        <td><a href=players.php?pid=63208&edition=5>gwnMarty</a></td>
        <td>1</td>
        <td>9871.880</td>
        <td>391.000</td>
    </tr>
    <tr>
        <td>2112</td>
        <td><a href=players.php?pid=28945&edition=5>AvocadoRL</a></td>
        <td>1</td>
        <td>9871.893</td>
        <td>392.000</td>
    </tr>
    <tr>
        <td>2113</td>
        <td><a href=players.php?pid=58618&edition=5>Archidamus12</a></td>
        <td>1</td>
        <td>9871.907</td>
        <td>393.000</td>
    </tr>
    <tr>
        <td>2114</td>
        <td><a href=players.php?pid=36773&edition=5>:KEKW:&nbsp;278&nbsp;enjoyer&nbsp;:KEKW:</a></td>
        <td>1</td>
        <td>9871.920</td>
        <td>394.000</td>
    </tr>
    <tr>
        <td>2115</td>
        <td><a href=players.php?pid=72094&edition=5>kmrebi</a></td>
        <td>1</td>
        <td>9871.933</td>
        <td>395.000</td>
    </tr>
    <tr>
        <td>2116</td>
        <td><a href=players.php?pid=2707&edition=5>haxGz</a></td>
        <td>1</td>
        <td>9871.973</td>
        <td>398.000</td>
    </tr>
    <tr>
        <td>2117</td>
        <td><a href=players.php?pid=52440&edition=5>gnipple</a></td>
        <td>1</td>
        <td>9871.973</td>
        <td>398.000</td>
    </tr>
    <tr>
        <td>2118</td>
        <td><a href=players.php?pid=67860&edition=5>ZaitY420</a></td>
        <td>1</td>
        <td>9871.987</td>
        <td>399.000</td>
    </tr>
    <tr>
        <td>2119</td>
        <td><a href=players.php?pid=67645&edition=5>hemmyo</a></td>
        <td>1</td>
        <td>9872.000</td>
        <td>400.000</td>
    </tr>
    <tr>
        <td>2120</td>
        <td><a href=players.php?pid=16738&edition=5><span style='color:#0000cc;'>Chat</span><span
                    style='color:#ffffff;'>Rennet</span></a></td>
        <td>1</td>
        <td>9872.013</td>
        <td>401.000</td>
    </tr>
    <tr>
        <td>2121</td>
        <td><a href=players.php?pid=31268&edition=5>OneHuntMan</a></td>
        <td>1</td>
        <td>9872.040</td>
        <td>403.000</td>
    </tr>
    <tr>
        <td>2122</td>
        <td><a href=players.php?pid=54229&edition=5>morbiius</a></td>
        <td>1</td>
        <td>9872.053</td>
        <td>404.000</td>
    </tr>
    <tr>
        <td>2123</td>
        <td><a href=players.php?pid=56760&edition=5>Sbon513</a></td>
        <td>1</td>
        <td>9872.053</td>
        <td>404.000</td>
    </tr>
    <tr>
        <td>2124</td>
        <td><a href=players.php?pid=67877&edition=5>DerGrolly</a></td>
        <td>1</td>
        <td>9872.093</td>
        <td>407.000</td>
    </tr>
    <tr>
        <td>2125</td>
        <td><a href=players.php?pid=66361&edition=5>Moto.toto</a></td>
        <td>1</td>
        <td>9872.107</td>
        <td>408.000</td>
    </tr>
    <tr>
        <td>2126</td>
        <td><a href=players.php?pid=21853&edition=5><span style='color:#66ff00;'>N</span><span
                    style='color:#88dd22;'>i</span><span style='color:#99aa44;'>n</span><span
                    style='color:#bb8866;'>e</span><span style='color:#cc5588;'>&nbsp;</span><span
                    style='color:#ee33aa;'>d</span><span style='color:#ff00cc;'>i</span><span
                    style='color:#ff00cc;'>e</span><span style='color:#dd33aa;'>&nbsp;</span><span
                    style='color:#bb5588;'>K</span><span style='color:#998866;'>a</span><span
                    style='color:#77aa44;'>t</span><span style='color:#55dd22;'>z</span><span
                    style='color:#33ff00;'>e</span></a></td>
        <td>1</td>
        <td>9872.107</td>
        <td>408.000</td>
    </tr>
    <tr>
        <td>2127</td>
        <td><a href=players.php?pid=66388&edition=5>mitherite1</a></td>
        <td>1</td>
        <td>9872.173</td>
        <td>413.000</td>
    </tr>
    <tr>
        <td>2128</td>
        <td><a href=players.php?pid=37530&edition=5>Jen007CZ</a></td>
        <td>1</td>
        <td>9872.173</td>
        <td>413.000</td>
    </tr>
    <tr>
        <td>2129</td>
        <td><a href=players.php?pid=68943&edition=5>StarboyTM_</a></td>
        <td>1</td>
        <td>9872.187</td>
        <td>414.000</td>
    </tr>
    <tr>
        <td>2130</td>
        <td><a href=players.php?pid=69882&edition=5>Poncefleur</a></td>
        <td>1</td>
        <td>9872.213</td>
        <td>416.000</td>
    </tr>
    <tr>
        <td>2131</td>
        <td><a href=players.php?pid=71002&edition=5>tacticalslurpi</a></td>
        <td>1</td>
        <td>9872.213</td>
        <td>416.000</td>
    </tr>
    <tr>
        <td>2132</td>
        <td><a href=players.php?pid=70947&edition=5><span style='color:#66ffff;'>S</span><span
                    style='color:#88ccff;'>h</span><span style='color:#aa99ff;'>l</span><span
                    style='color:#bb66ff;'>u</span><span style='color:#dd33ff;'>r</span><span
                    style='color:#ff00ff;'>p</span></a></td>
        <td>1</td>
        <td>9872.240</td>
        <td>418.000</td>
    </tr>
    <tr>
        <td>2133</td>
        <td><a href=players.php?pid=50257&edition=5><span style='color:#008800;'>A</span><span
                    style='color:#44aa44;'>l</span><span style='color:#88cc88;'>e</span><span
                    style='color:#bbddbb;'>x</span><span style='color:#ffffff;'>8</span><span
                    style='color:#ffffff;'>3</span><span style='color:#ffaaaa;'>7</span><span
                    style='color:#ff5555;'>я</span><span style='color:#ff0000;'>Ł</span></a></td>
        <td>1</td>
        <td>9872.253</td>
        <td>419.000</td>
    </tr>
    <tr>
        <td>2134</td>
        <td><a href=players.php?pid=51219&edition=5>Hipoglute</a></td>
        <td>1</td>
        <td>9872.320</td>
        <td>424.000</td>
    </tr>
    <tr>
        <td>2135</td>
        <td><a href=players.php?pid=65971&edition=5>BulleVirus</a></td>
        <td>1</td>
        <td>9872.347</td>
        <td>426.000</td>
    </tr>
    <tr>
        <td>2136</td>
        <td><a href=players.php?pid=20770&edition=5>XXsZsXX</a></td>
        <td>1</td>
        <td>9872.360</td>
        <td>427.000</td>
    </tr>
    <tr>
        <td>2137</td>
        <td><a href=players.php?pid=19193&edition=5>skateboring</a></td>
        <td>1</td>
        <td>9872.373</td>
        <td>428.000</td>
    </tr>
    <tr>
        <td>2138</td>
        <td><a href=players.php?pid=67246&edition=5>I3ishopB</a></td>
        <td>1</td>
        <td>9872.387</td>
        <td>429.000</td>
    </tr>
    <tr>
        <td>2139</td>
        <td><a href=players.php?pid=51998&edition=5>Deif361</a></td>
        <td>1</td>
        <td>9872.413</td>
        <td>431.000</td>
    </tr>
    <tr>
        <td>2140</td>
        <td><a href=players.php?pid=68880&edition=5>Smile_TM</a></td>
        <td>1</td>
        <td>9872.440</td>
        <td>433.000</td>
    </tr>
    <tr>
        <td>2141</td>
        <td><a href=players.php?pid=37737&edition=5>Ghostiorix</a></td>
        <td>1</td>
        <td>9872.507</td>
        <td>438.000</td>
    </tr>
    <tr>
        <td>2142</td>
        <td><a href=players.php?pid=72628&edition=5>Zane_TM</a></td>
        <td>1</td>
        <td>9872.507</td>
        <td>438.000</td>
    </tr>
    <tr>
        <td>2143</td>
        <td><a href=players.php?pid=313&edition=5>AurisTFG</a></td>
        <td>1</td>
        <td>9872.533</td>
        <td>440.000</td>
    </tr>
    <tr>
        <td>2144</td>
        <td><a href=players.php?pid=33087&edition=5>kayykayy</a></td>
        <td>1</td>
        <td>9872.533</td>
        <td>440.000</td>
    </tr>
    <tr>
        <td>2145</td>
        <td><a href=players.php?pid=19374&edition=5>GQRN</a></td>
        <td>1</td>
        <td>9872.560</td>
        <td>442.000</td>
    </tr>
    <tr>
        <td>2146</td>
        <td><a href=players.php?pid=27115&edition=5>BVDDY</a></td>
        <td>1</td>
        <td>9872.573</td>
        <td>443.000</td>
    </tr>
    <tr>
        <td>2147</td>
        <td><a href=players.php?pid=65841&edition=5>ONTTO_KALSKE</a></td>
        <td>1</td>
        <td>9872.587</td>
        <td>444.000</td>
    </tr>
    <tr>
        <td>2148</td>
        <td><a href=players.php?pid=6581&edition=5>Gekooo0</a></td>
        <td>1</td>
        <td>9872.600</td>
        <td>445.000</td>
    </tr>
    <tr>
        <td>2149</td>
        <td><a href=players.php?pid=56437&edition=5>Froggit714</a></td>
        <td>1</td>
        <td>9872.600</td>
        <td>445.000</td>
    </tr>
    <tr>
        <td>2150</td>
        <td><a href=players.php?pid=30973&edition=5>Z4CH2406</a></td>
        <td>1</td>
        <td>9872.613</td>
        <td>446.000</td>
    </tr>
    <tr>
        <td>2151</td>
        <td><a href=players.php?pid=66291&edition=5>Azur_TM</a></td>
        <td>1</td>
        <td>9872.653</td>
        <td>449.000</td>
    </tr>
    <tr>
        <td>2152</td>
        <td><a href=players.php?pid=39668&edition=5>Oi.Black.Rubber</a></td>
        <td>1</td>
        <td>9872.653</td>
        <td>449.000</td>
    </tr>
    <tr>
        <td>2153</td>
        <td><a href=players.php?pid=6844&edition=5>Daregenn_</a></td>
        <td>1</td>
        <td>9872.667</td>
        <td>450.000</td>
    </tr>
    <tr>
        <td>2154</td>
        <td><a href=players.php?pid=66341&edition=5>KillerCorp95</a></td>
        <td>1</td>
        <td>9872.667</td>
        <td>450.000</td>
    </tr>
    <tr>
        <td>2155</td>
        <td><a href=players.php?pid=37930&edition=5><span style='color:#00ff00;'>S</span><span
                    style='color:#44ff44;'>t</span><span style='color:#88ff88;'>e</span><span
                    style='color:#bbffbb;'>v</span><span style='color:#ffffff;'>e</span><span
                    style='color:#ffffff;'>n</span><span style='color:#ffbbbb;'>_</span><span
                    style='color:#ff8888;'>D</span><span style='color:#ff4444;'>s</span><span
                    style='color:#ff0000;'>M</span></a></td>
        <td>1</td>
        <td>9872.693</td>
        <td>452.000</td>
    </tr>
    <tr>
        <td>2156</td>
        <td><a href=players.php?pid=27856&edition=5>Jan_08.</a></td>
        <td>1</td>
        <td>9872.720</td>
        <td>454.000</td>
    </tr>
    <tr>
        <td>2157</td>
        <td><a href=players.php?pid=69871&edition=5>ramzzii_</a></td>
        <td>1</td>
        <td>9872.733</td>
        <td>455.000</td>
    </tr>
    <tr>
        <td>2158</td>
        <td><a href=players.php?pid=64000&edition=5>Escxet.</a></td>
        <td>1</td>
        <td>9872.773</td>
        <td>458.000</td>
    </tr>
    <tr>
        <td>2159</td>
        <td><a href=players.php?pid=22924&edition=5>Patriotew</a></td>
        <td>1</td>
        <td>9872.800</td>
        <td>460.000</td>
    </tr>
    <tr>
        <td>2160</td>
        <td><a href=players.php?pid=61770&edition=5>MoiKoin</a></td>
        <td>1</td>
        <td>9872.800</td>
        <td>460.000</td>
    </tr>
    <tr>
        <td>2161</td>
        <td><a href=players.php?pid=68670&edition=5>Jerkeypnut</a></td>
        <td>1</td>
        <td>9872.813</td>
        <td>461.000</td>
    </tr>
    <tr>
        <td>2162</td>
        <td><a href=players.php?pid=68668&edition=5>Fixx21</a></td>
        <td>1</td>
        <td>9872.893</td>
        <td>467.000</td>
    </tr>
    <tr>
        <td>2163</td>
        <td><a href=players.php?pid=72427&edition=5>Kuonsu</a></td>
        <td>1</td>
        <td>9872.947</td>
        <td>471.000</td>
    </tr>
    <tr>
        <td>2164</td>
        <td><a href=players.php?pid=67160&edition=5>synth.ice</a></td>
        <td>1</td>
        <td>9872.973</td>
        <td>473.000</td>
    </tr>
    <tr>
        <td>2165</td>
        <td><a href=players.php?pid=23062&edition=5>Petrus.TM</a></td>
        <td>1</td>
        <td>9873.000</td>
        <td>475.000</td>
    </tr>
    <tr>
        <td>2166</td>
        <td><a href=players.php?pid=68952&edition=5>nod32_tm</a></td>
        <td>1</td>
        <td>9873.000</td>
        <td>475.000</td>
    </tr>
    <tr>
        <td>2167</td>
        <td><a href=players.php?pid=70298&edition=5>Rubbj</a></td>
        <td>1</td>
        <td>9873.000</td>
        <td>475.000</td>
    </tr>
    <tr>
        <td>2168</td>
        <td><a href=players.php?pid=70346&edition=5>Kuzur0</a></td>
        <td>1</td>
        <td>9873.040</td>
        <td>478.000</td>
    </tr>
    <tr>
        <td>2169</td>
        <td><a href=players.php?pid=6255&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;</span><span style='color:#000000;'>Yuuzow</span></a></td>
        <td>1</td>
        <td>9873.093</td>
        <td>482.000</td>
    </tr>
    <tr>
        <td>2170</td>
        <td><a href=players.php?pid=68759&edition=5>Thiarm</a></td>
        <td>1</td>
        <td>9873.107</td>
        <td>483.000</td>
    </tr>
    <tr>
        <td>2171</td>
        <td><a href=players.php?pid=69572&edition=5>SSzaby23</a></td>
        <td>1</td>
        <td>9873.107</td>
        <td>483.000</td>
    </tr>
    <tr>
        <td>2172</td>
        <td><a href=players.php?pid=67210&edition=5>PickledGolf4107</a></td>
        <td>1</td>
        <td>9873.133</td>
        <td>485.000</td>
    </tr>
    <tr>
        <td>2173</td>
        <td><a href=players.php?pid=68000&edition=5>Ciiuuvv</a></td>
        <td>1</td>
        <td>9873.147</td>
        <td>486.000</td>
    </tr>
    <tr>
        <td>2174</td>
        <td><a href=players.php?pid=53414&edition=5>Toaghd</a></td>
        <td>1</td>
        <td>9873.160</td>
        <td>487.000</td>
    </tr>
    <tr>
        <td>2175</td>
        <td><a href=players.php?pid=45730&edition=5>hi412hi412hi412</a></td>
        <td>1</td>
        <td>9873.187</td>
        <td>489.000</td>
    </tr>
    <tr>
        <td>2176</td>
        <td><a href=players.php?pid=32323&edition=5>Charkie57</a></td>
        <td>1</td>
        <td>9873.200</td>
        <td>490.000</td>
    </tr>
    <tr>
        <td>2177</td>
        <td><a href=players.php?pid=69731&edition=5>Mistro343</a></td>
        <td>1</td>
        <td>9873.240</td>
        <td>493.000</td>
    </tr>
    <tr>
        <td>2178</td>
        <td><a href=players.php?pid=36161&edition=5>EmeraldJack_</a></td>
        <td>1</td>
        <td>9873.253</td>
        <td>494.000</td>
    </tr>
    <tr>
        <td>2179</td>
        <td><a href=players.php?pid=5881&edition=5>PluttenTM</a></td>
        <td>1</td>
        <td>9873.280</td>
        <td>496.000</td>
    </tr>
    <tr>
        <td>2180</td>
        <td><a href=players.php?pid=24058&edition=5>strikeoh</a></td>
        <td>1</td>
        <td>9873.280</td>
        <td>496.000</td>
    </tr>
    <tr>
        <td>2181</td>
        <td><a href=players.php?pid=72689&edition=5>silentninjaspy</a></td>
        <td>1</td>
        <td>9873.293</td>
        <td>497.000</td>
    </tr>
    <tr>
        <td>2182</td>
        <td><a href=players.php?pid=55022&edition=5>FlyntTM</a></td>
        <td>1</td>
        <td>9873.307</td>
        <td>498.000</td>
    </tr>
    <tr>
        <td>2183</td>
        <td><a href=players.php?pid=39212&edition=5>qualig</a></td>
        <td>1</td>
        <td>9873.333</td>
        <td>500.000</td>
    </tr>
    <tr>
        <td>2184</td>
        <td><a href=players.php?pid=164&edition=5>jovenium</a></td>
        <td>1</td>
        <td>9873.373</td>
        <td>503.000</td>
    </tr>
    <tr>
        <td>2185</td>
        <td><a href=players.php?pid=45848&edition=5>Connconn1023</a></td>
        <td>1</td>
        <td>9873.373</td>
        <td>503.000</td>
    </tr>
    <tr>
        <td>2186</td>
        <td><a href=players.php?pid=56047&edition=5>TwiLiiGhT5</a></td>
        <td>1</td>
        <td>9873.427</td>
        <td>507.000</td>
    </tr>
    <tr>
        <td>2187</td>
        <td><a href=players.php?pid=25761&edition=5>vitorlol22</a></td>
        <td>1</td>
        <td>9873.427</td>
        <td>507.000</td>
    </tr>
    <tr>
        <td>2188</td>
        <td><a href=players.php?pid=69630&edition=5>LouietheHog</a></td>
        <td>1</td>
        <td>9873.453</td>
        <td>509.000</td>
    </tr>
    <tr>
        <td>2189</td>
        <td><a href=players.php?pid=6615&edition=5>walshyIE</a></td>
        <td>1</td>
        <td>9873.467</td>
        <td>510.000</td>
    </tr>
    <tr>
        <td>2190</td>
        <td><a href=players.php?pid=68292&edition=5>benjipalmer</a></td>
        <td>1</td>
        <td>9873.480</td>
        <td>511.000</td>
    </tr>
    <tr>
        <td>2191</td>
        <td><a href=players.php?pid=53861&edition=5><span style='color:#9900ff;'>D</span><span
                    style='color:#8800ff;'>xs</span><span style='color:#7711ff;'>r</span><span
                    style='color:#6611ff;'>es</span><span style='color:#5511ff;'>p</span><span
                    style='color:#4422ff;'>e</span><span style='color:#3322ff;'>ct</span><span
                    style='color:#2222ff;'>f</span><span style='color:#1133ff;'>ul</span><span
                    style='color:#0033ff;'>l</span></a></td>
        <td>1</td>
        <td>9873.493</td>
        <td>512.000</td>
    </tr>
    <tr>
        <td>2192</td>
        <td><a href=players.php?pid=9707&edition=5>Alypse</a></td>
        <td>1</td>
        <td>9873.493</td>
        <td>512.000</td>
    </tr>
    <tr>
        <td>2193</td>
        <td><a href=players.php?pid=64907&edition=5>whiteshadow4113</a></td>
        <td>1</td>
        <td>9873.560</td>
        <td>517.000</td>
    </tr>
    <tr>
        <td>2194</td>
        <td><a href=players.php?pid=69320&edition=5>Mack_7</a></td>
        <td>1</td>
        <td>9873.560</td>
        <td>517.000</td>
    </tr>
    <tr>
        <td>2195</td>
        <td><a href=players.php?pid=52457&edition=5><span style='color:#00ffff;'>C</span><span
                    style='color:#88eeee;'>a</span><span style='color:#ffcccc;'>イ</span><span
                    style='color:#ffcccc;'>B</span><span style='color:#ffeeee;'>a</span><span
                    style='color:#ffffff;'>g</span></a></td>
        <td>1</td>
        <td>9873.573</td>
        <td>518.000</td>
    </tr>
    <tr>
        <td>2196</td>
        <td><a href=players.php?pid=51979&edition=5>pupspopo</a></td>
        <td>1</td>
        <td>9873.587</td>
        <td>519.000</td>
    </tr>
    <tr>
        <td>2197</td>
        <td><a href=players.php?pid=55958&edition=5>Flip_Kibler</a></td>
        <td>1</td>
        <td>9873.600</td>
        <td>520.000</td>
    </tr>
    <tr>
        <td>2198</td>
        <td><a href=players.php?pid=34041&edition=5><span
                    style='color:#00ffff;font-weight:bold;'>JoakimTheBot</span></a></td>
        <td>1</td>
        <td>9873.627</td>
        <td>522.000</td>
    </tr>
    <tr>
        <td>2199</td>
        <td><a href=players.php?pid=1424&edition=5>toofoo.</a></td>
        <td>1</td>
        <td>9873.627</td>
        <td>522.000</td>
    </tr>
    <tr>
        <td>2200</td>
        <td><a href=players.php?pid=69014&edition=5>z4go</a></td>
        <td>1</td>
        <td>9873.653</td>
        <td>524.000</td>
    </tr>
    <tr>
        <td>2201</td>
        <td><a href=players.php?pid=3164&edition=5>Quentinoche3360</a></td>
        <td>1</td>
        <td>9873.653</td>
        <td>524.000</td>
    </tr>
    <tr>
        <td>2202</td>
        <td><a href=players.php?pid=228&edition=5>GetsugoTenshu</a></td>
        <td>1</td>
        <td>9873.720</td>
        <td>529.000</td>
    </tr>
    <tr>
        <td>2203</td>
        <td><a href=players.php?pid=26001&edition=5><span style='color:#22dd22;font-weight:bold;'>P</span><span
                    style='color:#779977;font-weight:bold;'>i</span><span
                    style='color:#ff33ee;font-weight:bold;'>X</span><span
                    style='color:#bb4466;font-weight:bold;'>D</span><span
                    style='color:#995500;font-weight:bold;'>D</span>&nbsp;:wokege:</a></td>
        <td>1</td>
        <td>9873.733</td>
        <td>530.000</td>
    </tr>
    <tr>
        <td>2204</td>
        <td><a href=players.php?pid=71786&edition=5>Schublin</a></td>
        <td>1</td>
        <td>9873.747</td>
        <td>531.000</td>
    </tr>
    <tr>
        <td>2205</td>
        <td><a href=players.php?pid=67582&edition=5><span style='color:#ff0000;'>S</span><span
                    style='color:#ff1122;'>h</span><span style='color:#ff1144;'>i</span><span
                    style='color:#ff2255;'>n</span><span style='color:#ff2277;'>a</span><span
                    style='color:#ff3399;'>i</span></a></td>
        <td>1</td>
        <td>9873.760</td>
        <td>532.000</td>
    </tr>
    <tr>
        <td>2206</td>
        <td><a href=players.php?pid=33602&edition=5>Rap10tor</a></td>
        <td>1</td>
        <td>9873.840</td>
        <td>538.000</td>
    </tr>
    <tr>
        <td>2207</td>
        <td><a href=players.php?pid=15573&edition=5><span style='color:#0000ff;font-weight:bold;'>Crackzy</span></a>
        </td>
        <td>1</td>
        <td>9873.840</td>
        <td>538.000</td>
    </tr>
    <tr>
        <td>2208</td>
        <td><a href=players.php?pid=54231&edition=5>RayzeTwitch</a></td>
        <td>1</td>
        <td>9873.853</td>
        <td>539.000</td>
    </tr>
    <tr>
        <td>2209</td>
        <td><a href=players.php?pid=66074&edition=5>AnEmptyRealm</a></td>
        <td>1</td>
        <td>9873.853</td>
        <td>539.000</td>
    </tr>
    <tr>
        <td>2210</td>
        <td><a href=players.php?pid=66302&edition=5>PengOCE</a></td>
        <td>1</td>
        <td>9873.867</td>
        <td>540.000</td>
    </tr>
    <tr>
        <td>2211</td>
        <td><a href=players.php?pid=45847&edition=5>Sebeqeq_TM</a></td>
        <td>1</td>
        <td>9873.893</td>
        <td>542.000</td>
    </tr>
    <tr>
        <td>2212</td>
        <td><a href=players.php?pid=69058&edition=5>Jeff--</a></td>
        <td>1</td>
        <td>9873.933</td>
        <td>545.000</td>
    </tr>
    <tr>
        <td>2213</td>
        <td><a href=players.php?pid=20474&edition=5>damaaTM</a></td>
        <td>1</td>
        <td>9873.933</td>
        <td>545.000</td>
    </tr>
    <tr>
        <td>2214</td>
        <td><a href=players.php?pid=67091&edition=5>rilouuu</a></td>
        <td>1</td>
        <td>9873.947</td>
        <td>546.000</td>
    </tr>
    <tr>
        <td>2215</td>
        <td><a href=players.php?pid=42211&edition=5><span style='color:#ff0000;'>N</span><span
                    style='color:#ff2211;'>i</span><span style='color:#ff3322;'>b</span><span
                    style='color:#ff5533;'>b</span><span style='color:#ff6644;'>l</span><span
                    style='color:#ff8855;'>e</span><span style='color:#ff9966;'>s</span></a></td>
        <td>1</td>
        <td>9873.960</td>
        <td>547.000</td>
    </tr>
    <tr>
        <td>2216</td>
        <td><a href=players.php?pid=69765&edition=5>coolgreen106</a></td>
        <td>1</td>
        <td>9874.013</td>
        <td>551.000</td>
    </tr>
    <tr>
        <td>2217</td>
        <td><a href=players.php?pid=21452&edition=5>MasonUI</a></td>
        <td>1</td>
        <td>9874.013</td>
        <td>551.000</td>
    </tr>
    <tr>
        <td>2218</td>
        <td><a href=players.php?pid=53533&edition=5>kamcisz</a></td>
        <td>1</td>
        <td>9874.027</td>
        <td>552.000</td>
    </tr>
    <tr>
        <td>2219</td>
        <td><a href=players.php?pid=45207&edition=5>Superman2710</a></td>
        <td>1</td>
        <td>9874.027</td>
        <td>552.000</td>
    </tr>
    <tr>
        <td>2220</td>
        <td><a href=players.php?pid=70782&edition=5>Lokiifu</a></td>
        <td>1</td>
        <td>9874.053</td>
        <td>554.000</td>
    </tr>
    <tr>
        <td>2221</td>
        <td><a href=players.php?pid=71808&edition=5>szepfiu</a></td>
        <td>1</td>
        <td>9874.053</td>
        <td>554.000</td>
    </tr>
    <tr>
        <td>2222</td>
        <td><a href=players.php?pid=68255&edition=5>harrymanback133</a></td>
        <td>1</td>
        <td>9874.107</td>
        <td>558.000</td>
    </tr>
    <tr>
        <td>2223</td>
        <td><a href=players.php?pid=25026&edition=5>R21_DeViiL</a></td>
        <td>1</td>
        <td>9874.120</td>
        <td>559.000</td>
    </tr>
    <tr>
        <td>2224</td>
        <td><a href=players.php?pid=17505&edition=5><span style='color:#0033cc;'>C</span><span
                    style='color:#0044bb;'>a</span><span style='color:#004499;'>r</span><span
                    style='color:#005588;'>f</span><span style='color:#006677;'>r</span><span
                    style='color:#006655;'>e</span><span style='color:#007744;'>a</span><span
                    style='color:#008833;'>k</span><span style='color:#008811;'>4</span><span
                    style='color:#009900;'>4</span></a></td>
        <td>1</td>
        <td>9874.147</td>
        <td>561.000</td>
    </tr>
    <tr>
        <td>2225</td>
        <td><a href=players.php?pid=42478&edition=5>xTannerS</a></td>
        <td>1</td>
        <td>9874.173</td>
        <td>563.000</td>
    </tr>
    <tr>
        <td>2226</td>
        <td><a href=players.php?pid=58583&edition=5>GTD_Flofunxpd</a></td>
        <td>1</td>
        <td>9874.213</td>
        <td>566.000</td>
    </tr>
    <tr>
        <td>2227</td>
        <td><a href=players.php?pid=16638&edition=5>TheOnlyBegrip</a></td>
        <td>1</td>
        <td>9874.253</td>
        <td>569.000</td>
    </tr>
    <tr>
        <td>2228</td>
        <td><a href=players.php?pid=68739&edition=5>orb..-</a></td>
        <td>1</td>
        <td>9874.267</td>
        <td>570.000</td>
    </tr>
    <tr>
        <td>2229</td>
        <td><a href=players.php?pid=25598&edition=5>Norororok</a></td>
        <td>1</td>
        <td>9874.280</td>
        <td>571.000</td>
    </tr>
    <tr>
        <td>2230</td>
        <td><a href=players.php?pid=35948&edition=5><span
                    style='color:#331177;font-style:italic;font-weight:bold;'>N</span><span
                    style='color:#331177;font-style:italic;font-weight:bold;'>u</span><span
                    style='color:#441188;font-style:italic;font-weight:bold;'>n</span><span
                    style='color:#551188;font-style:italic;font-weight:bold;'>i</span><span
                    style='color:#661188;font-style:italic;font-weight:bold;'>t</span><span
                    style='color:#662299;font-style:italic;font-weight:bold;'>e</span><span
                    style='color:#772299;font-style:italic;font-weight:bold;'>q</span></a></td>
        <td>1</td>
        <td>9874.293</td>
        <td>572.000</td>
    </tr>
    <tr>
        <td>2231</td>
        <td><a href=players.php?pid=32145&edition=5>TLennyy</a></td>
        <td>1</td>
        <td>9874.293</td>
        <td>572.000</td>
    </tr>
    <tr>
        <td>2232</td>
        <td><a href=players.php?pid=47162&edition=5>invisiblecat08</a></td>
        <td>1</td>
        <td>9874.400</td>
        <td>580.000</td>
    </tr>
    <tr>
        <td>2233</td>
        <td><a href=players.php?pid=66726&edition=5>joriss11</a></td>
        <td>1</td>
        <td>9874.413</td>
        <td>581.000</td>
    </tr>
    <tr>
        <td>2234</td>
        <td><a href=players.php?pid=46693&edition=5>KillaWRX909</a></td>
        <td>1</td>
        <td>9874.453</td>
        <td>584.000</td>
    </tr>
    <tr>
        <td>2235</td>
        <td><a href=players.php?pid=50526&edition=5>Astro386</a></td>
        <td>1</td>
        <td>9874.493</td>
        <td>587.000</td>
    </tr>
    <tr>
        <td>2236</td>
        <td><a href=players.php?pid=67788&edition=5>MisterDuggy</a></td>
        <td>1</td>
        <td>9874.507</td>
        <td>588.000</td>
    </tr>
    <tr>
        <td>2237</td>
        <td><a href=players.php?pid=1695&edition=5><span style='color:#ff3366;'>Si</span><span
                    style='color:#ff4466;'>syp</span><span style='color:#ee4455;'>h</span><span
                    style='color:#ee5555;'>ean&nbsp;</span><span style='color:#ee6655;'>ins</span><span
                    style='color:#dd6644;'>u</span><span style='color:#dd7744;'>rrec</span><span
                    style='color:#dd8844;'>tio</span><span style='color:#cc8833;'>n</span><span
                    style='color:#cc9933;'>ist</span></a></td>
        <td>1</td>
        <td>9874.533</td>
        <td>590.000</td>
    </tr>
    <tr>
        <td>2238</td>
        <td><a href=players.php?pid=67339&edition=5>Omulwaanyi</a></td>
        <td>1</td>
        <td>9874.547</td>
        <td>591.000</td>
    </tr>
    <tr>
        <td>2239</td>
        <td><a href=players.php?pid=61871&edition=5>b:owo:<span
                    style='color:#7711cc;font-style:italic;font-weight:bold;'>F</span><span
                    style='color:#7711bb;font-style:italic;font-weight:bold;'>д</span><span
                    style='color:#6611aa;font-style:italic;font-weight:bold;'>&tau;</span><span
                    style='color:#661199;font-style:italic;font-weight:bold;'>ĩ</span><span
                    style='color:#660088;font-style:italic;font-weight:bold;'>ŧ</span><span
                    style='color:#660066;font-style:italic;font-weight:bold;'>Ί:owo:</span></a></td>
        <td>1</td>
        <td>9874.560</td>
        <td>592.000</td>
    </tr>
    <tr>
        <td>2240</td>
        <td><a href=players.php?pid=72435&edition=5>CATninja58</a></td>
        <td>1</td>
        <td>9874.560</td>
        <td>592.000</td>
    </tr>
    <tr>
        <td>2241</td>
        <td><a href=players.php?pid=65678&edition=5>Zaino1</a></td>
        <td>1</td>
        <td>9874.573</td>
        <td>593.000</td>
    </tr>
    <tr>
        <td>2242</td>
        <td><a href=players.php?pid=311&edition=5>CrazzTM</a></td>
        <td>1</td>
        <td>9874.587</td>
        <td>594.000</td>
    </tr>
    <tr>
        <td>2243</td>
        <td><a href=players.php?pid=68233&edition=5>Im.Demon</a></td>
        <td>1</td>
        <td>9874.600</td>
        <td>595.000</td>
    </tr>
    <tr>
        <td>2244</td>
        <td><a href=players.php?pid=7737&edition=5>jokey___</a></td>
        <td>1</td>
        <td>9874.613</td>
        <td>596.000</td>
    </tr>
    <tr>
        <td>2245</td>
        <td><a href=players.php?pid=53622&edition=5>snoepiew</a></td>
        <td>1</td>
        <td>9874.613</td>
        <td>596.000</td>
    </tr>
    <tr>
        <td>2246</td>
        <td><a href=players.php?pid=68954&edition=5>Xog_</a></td>
        <td>1</td>
        <td>9874.613</td>
        <td>596.000</td>
    </tr>
    <tr>
        <td>2247</td>
        <td><a href=players.php?pid=69316&edition=5>Rovvit</a></td>
        <td>1</td>
        <td>9874.653</td>
        <td>599.000</td>
    </tr>
    <tr>
        <td>2248</td>
        <td><a href=players.php?pid=63495&edition=5>uuwti</a></td>
        <td>1</td>
        <td>9874.653</td>
        <td>599.000</td>
    </tr>
    <tr>
        <td>2249</td>
        <td><a href=players.php?pid=42508&edition=5>Kstarwind42</a></td>
        <td>1</td>
        <td>9874.667</td>
        <td>600.000</td>
    </tr>
    <tr>
        <td>2250</td>
        <td><a href=players.php?pid=71087&edition=5>yoan860</a></td>
        <td>1</td>
        <td>9874.667</td>
        <td>600.000</td>
    </tr>
    <tr>
        <td>2251</td>
        <td><a href=players.php?pid=63271&edition=5>zZdxcyZz</a></td>
        <td>1</td>
        <td>9874.693</td>
        <td>602.000</td>
    </tr>
    <tr>
        <td>2252</td>
        <td><a href=players.php?pid=30542&edition=5><span
                    style='color:#ff0000;'>Micha:e:lJackson&nbsp;:pepepoint:&nbsp;</span><span
                    style='color:#ffffff;'>[1]</span></a></td>
        <td>1</td>
        <td>9874.693</td>
        <td>602.000</td>
    </tr>
    <tr>
        <td>2253</td>
        <td><a href=players.php?pid=47864&edition=5>wortaxi</a></td>
        <td>1</td>
        <td>9874.693</td>
        <td>602.000</td>
    </tr>
    <tr>
        <td>2254</td>
        <td><a href=players.php?pid=70225&edition=5>SSGeorgie17</a></td>
        <td>1</td>
        <td>9874.747</td>
        <td>606.000</td>
    </tr>
    <tr>
        <td>2255</td>
        <td><a href=players.php?pid=67665&edition=5>Gorax1mus</a></td>
        <td>1</td>
        <td>9874.760</td>
        <td>607.000</td>
    </tr>
    <tr>
        <td>2256</td>
        <td><a href=players.php?pid=31567&edition=5>tortuman</a></td>
        <td>1</td>
        <td>9874.787</td>
        <td>609.000</td>
    </tr>
    <tr>
        <td>2257</td>
        <td><a href=players.php?pid=66783&edition=5>Bananpalmen</a></td>
        <td>1</td>
        <td>9874.813</td>
        <td>611.000</td>
    </tr>
    <tr>
        <td>2258</td>
        <td><a href=players.php?pid=60781&edition=5>Ozzymandius45</a></td>
        <td>1</td>
        <td>9874.813</td>
        <td>611.000</td>
    </tr>
    <tr>
        <td>2259</td>
        <td><a href=players.php?pid=44584&edition=5>guest-bIVT5bsn</a></td>
        <td>1</td>
        <td>9874.827</td>
        <td>612.000</td>
    </tr>
    <tr>
        <td>2260</td>
        <td><a href=players.php?pid=63171&edition=5>xigorxx28</a></td>
        <td>1</td>
        <td>9874.853</td>
        <td>614.000</td>
    </tr>
    <tr>
        <td>2261</td>
        <td><a href=players.php?pid=47728&edition=5>WolfyX</a></td>
        <td>1</td>
        <td>9874.880</td>
        <td>616.000</td>
    </tr>
    <tr>
        <td>2262</td>
        <td><a href=players.php?pid=53109&edition=5>Franswazig</a></td>
        <td>1</td>
        <td>9874.893</td>
        <td>617.000</td>
    </tr>
    <tr>
        <td>2263</td>
        <td><a href=players.php?pid=52785&edition=5>Thorsidius</a></td>
        <td>1</td>
        <td>9874.893</td>
        <td>617.000</td>
    </tr>
    <tr>
        <td>2264</td>
        <td><a href=players.php?pid=9187&edition=5><span style='color:#00eeff;'>S</span><span
                    style='color:#88aaee;'>c</span><span style='color:#ff55ee;'>e</span><span
                    style='color:#ff88ee;'>p</span><span style='color:#ffccff;'>t</span><span
                    style='color:#ffffff;'>i</span><span style='color:#ffccff;'>c</span><span
                    style='color:#ff88ee;'>H</span><span style='color:#ff55ee;'>a</span><span
                    style='color:#cc77ee;'>m</span><span style='color:#9999ee;'>s</span><span
                    style='color:#66aaee;'>t</span><span style='color:#33ccff;'>e</span><span
                    style='color:#00eeff;'>r</span></a></td>
        <td>1</td>
        <td>9874.920</td>
        <td>619.000</td>
    </tr>
    <tr>
        <td>2265</td>
        <td><a href=players.php?pid=61808&edition=5><span style='color:#ffffff;'>Logan</span><span
                    style='color:#ee0000;font-style:italic;font-weight:bold;'>.wav</span><span
                    style='color:#cc0000;font-style:italic;font-weight:bold;'>&nbsp;</span></a></td>
        <td>1</td>
        <td>9874.987</td>
        <td>624.000</td>
    </tr>
    <tr>
        <td>2266</td>
        <td><a href=players.php?pid=52958&edition=5>RauchendesReGaL</a></td>
        <td>1</td>
        <td>9875.000</td>
        <td>625.000</td>
    </tr>
    <tr>
        <td>2267</td>
        <td><a href=players.php?pid=70544&edition=5>DK37</a></td>
        <td>1</td>
        <td>9875.000</td>
        <td>625.000</td>
    </tr>
    <tr>
        <td>2268</td>
        <td><a href=players.php?pid=32525&edition=5>Classy_Pika32</a></td>
        <td>1</td>
        <td>9875.013</td>
        <td>626.000</td>
    </tr>
    <tr>
        <td>2269</td>
        <td><a href=players.php?pid=56018&edition=5>Meeco.</a></td>
        <td>1</td>
        <td>9875.053</td>
        <td>629.000</td>
    </tr>
    <tr>
        <td>2270</td>
        <td><a href=players.php?pid=68205&edition=5>KILLLLLLLLLLYSF</a></td>
        <td>1</td>
        <td>9875.067</td>
        <td>630.000</td>
    </tr>
    <tr>
        <td>2271</td>
        <td><a href=players.php?pid=48849&edition=5><span style='color:#ff0099;'>V</span><span
                    style='color:#ff0066;'>o</span><span style='color:#ff0033;'>r</span><span
                    style='color:#ff0000;'>t</span><span style='color:#ff0000;'>r</span><span
                    style='color:#ff0022;'>o</span><span style='color:#ff0033;'>x</span></a></td>
        <td>1</td>
        <td>9875.080</td>
        <td>631.000</td>
    </tr>
    <tr>
        <td>2272</td>
        <td><a href=players.php?pid=66310&edition=5>JentoXboy</a></td>
        <td>1</td>
        <td>9875.080</td>
        <td>631.000</td>
    </tr>
    <tr>
        <td>2273</td>
        <td><a href=players.php?pid=22965&edition=5>BacchusCDI</a></td>
        <td>1</td>
        <td>9875.147</td>
        <td>636.000</td>
    </tr>
    <tr>
        <td>2274</td>
        <td><a href=players.php?pid=41427&edition=5><span style='color:#ff3333;'>sh4</span><span
                    style='color:#cc0066;'>d0w</span><span style='color:#cc0000;'>m4x</span></a></td>
        <td>1</td>
        <td>9875.173</td>
        <td>638.000</td>
    </tr>
    <tr>
        <td>2275</td>
        <td><a href=players.php?pid=18903&edition=5>ZockiTm</a></td>
        <td>1</td>
        <td>9875.187</td>
        <td>639.000</td>
    </tr>
    <tr>
        <td>2276</td>
        <td><a href=players.php?pid=67481&edition=5><span style='color:#ff0000;'>Th</span><span
                    style='color:#ffffff;'>ie</span><span style='color:#0000ff;'>sk</span><span
                    style='color:#ffff00;'>e_</span><span style='color:#000000;'>04</span></a></td>
        <td>1</td>
        <td>9875.200</td>
        <td>640.000</td>
    </tr>
    <tr>
        <td>2277</td>
        <td><a href=players.php?pid=68321&edition=5>PhenomenaTM</a></td>
        <td>1</td>
        <td>9875.240</td>
        <td>643.000</td>
    </tr>
    <tr>
        <td>2278</td>
        <td><a href=players.php?pid=66578&edition=5>Scholli_07</a></td>
        <td>1</td>
        <td>9875.240</td>
        <td>643.000</td>
    </tr>
    <tr>
        <td>2279</td>
        <td><a href=players.php?pid=59578&edition=5>JimiBoby</a></td>
        <td>1</td>
        <td>9875.293</td>
        <td>647.000</td>
    </tr>
    <tr>
        <td>2280</td>
        <td><a href=players.php?pid=38509&edition=5>Lauelia</a></td>
        <td>1</td>
        <td>9875.307</td>
        <td>648.000</td>
    </tr>
    <tr>
        <td>2281</td>
        <td><a href=players.php?pid=35788&edition=5>mr_treeee</a></td>
        <td>1</td>
        <td>9875.320</td>
        <td>649.000</td>
    </tr>
    <tr>
        <td>2282</td>
        <td><a href=players.php?pid=46210&edition=5>Davidercool</a></td>
        <td>1</td>
        <td>9875.320</td>
        <td>649.000</td>
    </tr>
    <tr>
        <td>2283</td>
        <td><a href=players.php?pid=68555&edition=5>StaticTc</a></td>
        <td>1</td>
        <td>9875.333</td>
        <td>650.000</td>
    </tr>
    <tr>
        <td>2284</td>
        <td><a href=players.php?pid=28975&edition=5>LucaMT12</a></td>
        <td>1</td>
        <td>9875.333</td>
        <td>650.000</td>
    </tr>
    <tr>
        <td>2285</td>
        <td><a href=players.php?pid=7662&edition=5>DarioTM_</a></td>
        <td>1</td>
        <td>9875.347</td>
        <td>651.000</td>
    </tr>
    <tr>
        <td>2286</td>
        <td><a href=players.php?pid=72250&edition=5>Steve_dariu090</a></td>
        <td>1</td>
        <td>9875.347</td>
        <td>651.000</td>
    </tr>
    <tr>
        <td>2287</td>
        <td><a href=players.php?pid=43329&edition=5><span style='color:#55eeff;'>|</span><span
                    style='color:#8833ff;'>meg</span><span style='color:#55eeff;'>|</span></a></td>
        <td>1</td>
        <td>9875.360</td>
        <td>652.000</td>
    </tr>
    <tr>
        <td>2288</td>
        <td><a href=players.php?pid=71274&edition=5>BforBigSmoke</a></td>
        <td>1</td>
        <td>9875.373</td>
        <td>653.000</td>
    </tr>
    <tr>
        <td>2289</td>
        <td><a href=players.php?pid=70850&edition=5>K-Ruoka</a></td>
        <td>1</td>
        <td>9875.373</td>
        <td>653.000</td>
    </tr>
    <tr>
        <td>2290</td>
        <td><a href=players.php?pid=6797&edition=5>Longcreek</a></td>
        <td>1</td>
        <td>9875.413</td>
        <td>656.000</td>
    </tr>
    <tr>
        <td>2291</td>
        <td><a href=players.php?pid=39240&edition=5>EAS1ER</a></td>
        <td>1</td>
        <td>9875.467</td>
        <td>660.000</td>
    </tr>
    <tr>
        <td>2292</td>
        <td><a href=players.php?pid=69843&edition=5>Dinosaurus_Fila</a></td>
        <td>1</td>
        <td>9875.547</td>
        <td>666.000</td>
    </tr>
    <tr>
        <td>2293</td>
        <td><a href=players.php?pid=70860&edition=5>Jorlax_</a></td>
        <td>1</td>
        <td>9875.587</td>
        <td>669.000</td>
    </tr>
    <tr>
        <td>2294</td>
        <td><a href=players.php?pid=72255&edition=5>hot_killerz</a></td>
        <td>1</td>
        <td>9875.587</td>
        <td>669.000</td>
    </tr>
    <tr>
        <td>2295</td>
        <td><a href=players.php?pid=72683&edition=5>yeahigez</a></td>
        <td>1</td>
        <td>9875.587</td>
        <td>669.000</td>
    </tr>
    <tr>
        <td>2296</td>
        <td><a href=players.php?pid=38815&edition=5>Jakoshi45</a></td>
        <td>1</td>
        <td>9875.600</td>
        <td>670.000</td>
    </tr>
    <tr>
        <td>2297</td>
        <td><a href=players.php?pid=69883&edition=5>Bytell2</a></td>
        <td>1</td>
        <td>9875.600</td>
        <td>670.000</td>
    </tr>
    <tr>
        <td>2298</td>
        <td><a href=players.php?pid=22372&edition=5>ZackLimp</a></td>
        <td>1</td>
        <td>9875.613</td>
        <td>671.000</td>
    </tr>
    <tr>
        <td>2299</td>
        <td><a href=players.php?pid=60950&edition=5>BestKackyYet</a></td>
        <td>1</td>
        <td>9875.627</td>
        <td>672.000</td>
    </tr>
    <tr>
        <td>2300</td>
        <td><a href=players.php?pid=72356&edition=5>Leg4t0r</a></td>
        <td>1</td>
        <td>9875.627</td>
        <td>672.000</td>
    </tr>
    <tr>
        <td>2301</td>
        <td><a href=players.php?pid=9542&edition=5><span
                    style='color:#66ddff;font-style:italic;letter-spacing: -0.1em;font-size:smaller'>つき&nbsp;</span><span
                    style='color:#ffccee;font-style:italic;letter-spacing: -0.1em;font-size:smaller'>&laquo;&nbsp;</span><span
                    style='color:#ffffff;font-style:italic;letter-spacing: -0.1em;font-size:smaller'>у&upsilon;&omega;&upsilon;&kappa;ו</span><span
                    style='color:#ffccee;font-style:italic;letter-spacing: -0.1em;font-size:smaller'>ै.&nbsp;&raquo;</span><span
                    style='color:#66ddff;font-style:italic;letter-spacing: -0.1em;font-size:smaller'>&nbsp;ほし</span></a>
        </td>
        <td>1</td>
        <td>9875.667</td>
        <td>675.000</td>
    </tr>
    <tr>
        <td>2302</td>
        <td><a href=players.php?pid=68573&edition=5>Victorsar21</a></td>
        <td>1</td>
        <td>9875.693</td>
        <td>677.000</td>
    </tr>
    <tr>
        <td>2303</td>
        <td><a href=players.php?pid=62362&edition=5>IceL1ght</a></td>
        <td>1</td>
        <td>9875.707</td>
        <td>678.000</td>
    </tr>
    <tr>
        <td>2304</td>
        <td><a href=players.php?pid=68467&edition=5>Nidhogg369</a></td>
        <td>1</td>
        <td>9875.720</td>
        <td>679.000</td>
    </tr>
    <tr>
        <td>2305</td>
        <td><a href=players.php?pid=13465&edition=5>vViper_</a></td>
        <td>1</td>
        <td>9875.733</td>
        <td>680.000</td>
    </tr>
    <tr>
        <td>2306</td>
        <td><a href=players.php?pid=32745&edition=5><span style='color:#00ccff;'>s</span><span
                    style='color:#33ddff;'>i</span><span style='color:#66ddff;'>l</span><span
                    style='color:#88eeee;'>e</span><span style='color:#bbeeee;'>n</span><span
                    style='color:#bbeeee;'>t</span><span style='color:#cceeee;'>F</span><span
                    style='color:#eeffff;'>e</span><span style='color:#ffffff;'>z</span></a></td>
        <td>1</td>
        <td>9875.747</td>
        <td>681.000</td>
    </tr>
    <tr>
        <td>2307</td>
        <td><a href=players.php?pid=30972&edition=5>Le0nardo_.</a></td>
        <td>1</td>
        <td>9875.747</td>
        <td>681.000</td>
    </tr>
    <tr>
        <td>2308</td>
        <td><a href=players.php?pid=65574&edition=5>zaury.</a></td>
        <td>1</td>
        <td>9875.760</td>
        <td>682.000</td>
    </tr>
    <tr>
        <td>2309</td>
        <td><a href=players.php?pid=69475&edition=5>Bejebel4321</a></td>
        <td>1</td>
        <td>9875.773</td>
        <td>683.000</td>
    </tr>
    <tr>
        <td>2310</td>
        <td><a href=players.php?pid=52051&edition=5>Hap</a></td>
        <td>1</td>
        <td>9875.787</td>
        <td>684.000</td>
    </tr>
    <tr>
        <td>2311</td>
        <td><a href=players.php?pid=25314&edition=5><span style='color:#88ccee;font-style:italic;'>Fr0z3n</span></a>
        </td>
        <td>1</td>
        <td>9875.800</td>
        <td>685.000</td>
    </tr>
    <tr>
        <td>2312</td>
        <td><a href=players.php?pid=52509&edition=5>ChipJuni2022</a></td>
        <td>1</td>
        <td>9875.800</td>
        <td>685.000</td>
    </tr>
    <tr>
        <td>2313</td>
        <td><a href=players.php?pid=30987&edition=5>PokeuuuTM</a></td>
        <td>1</td>
        <td>9875.827</td>
        <td>687.000</td>
    </tr>
    <tr>
        <td>2314</td>
        <td><a href=players.php?pid=66419&edition=5>SirMilo900</a></td>
        <td>1</td>
        <td>9875.880</td>
        <td>691.000</td>
    </tr>
    <tr>
        <td>2315</td>
        <td><a href=players.php?pid=46178&edition=5>PooEater28</a></td>
        <td>1</td>
        <td>9875.920</td>
        <td>694.000</td>
    </tr>
    <tr>
        <td>2316</td>
        <td><a href=players.php?pid=44041&edition=5>thijnmens</a></td>
        <td>1</td>
        <td>9875.920</td>
        <td>694.000</td>
    </tr>
    <tr>
        <td>2317</td>
        <td><a href=players.php?pid=70452&edition=5>UselessWater_tm</a></td>
        <td>1</td>
        <td>9875.920</td>
        <td>694.000</td>
    </tr>
    <tr>
        <td>2318</td>
        <td><a href=players.php?pid=32766&edition=5>Mc_Cheezey</a></td>
        <td>1</td>
        <td>9875.973</td>
        <td>698.000</td>
    </tr>
    <tr>
        <td>2319</td>
        <td><a href=players.php?pid=785&edition=5>GoldPush</a></td>
        <td>1</td>
        <td>9875.987</td>
        <td>699.000</td>
    </tr>
    <tr>
        <td>2320</td>
        <td><a href=players.php?pid=34055&edition=5>JellisUK</a></td>
        <td>1</td>
        <td>9876.000</td>
        <td>700.000</td>
    </tr>
    <tr>
        <td>2321</td>
        <td><a href=players.php?pid=36448&edition=5><span style='color:#6600cc;'>R3VRB</span></a></td>
        <td>1</td>
        <td>9876.013</td>
        <td>701.000</td>
    </tr>
    <tr>
        <td>2322</td>
        <td><a href=players.php?pid=55533&edition=5>Matheski</a></td>
        <td>1</td>
        <td>9876.053</td>
        <td>704.000</td>
    </tr>
    <tr>
        <td>2323</td>
        <td><a href=players.php?pid=36808&edition=5>beefjurky1724</a></td>
        <td>1</td>
        <td>9876.053</td>
        <td>704.000</td>
    </tr>
    <tr>
        <td>2324</td>
        <td><a href=players.php?pid=25272&edition=5>thethep1lot</a></td>
        <td>1</td>
        <td>9876.067</td>
        <td>705.000</td>
    </tr>
    <tr>
        <td>2325</td>
        <td><a href=players.php?pid=17213&edition=5>Hitsohi</a></td>
        <td>1</td>
        <td>9876.093</td>
        <td>707.000</td>
    </tr>
    <tr>
        <td>2326</td>
        <td><a href=players.php?pid=16313&edition=5>danger97</a></td>
        <td>1</td>
        <td>9876.107</td>
        <td>708.000</td>
    </tr>
    <tr>
        <td>2327</td>
        <td><a href=players.php?pid=66684&edition=5>Msj1910</a></td>
        <td>1</td>
        <td>9876.187</td>
        <td>714.000</td>
    </tr>
    <tr>
        <td>2328</td>
        <td><a href=players.php?pid=30676&edition=5>Kresse05</a></td>
        <td>1</td>
        <td>9876.187</td>
        <td>714.000</td>
    </tr>
    <tr>
        <td>2329</td>
        <td><a href=players.php?pid=37893&edition=5>elwiwiTM</a></td>
        <td>1</td>
        <td>9876.200</td>
        <td>715.000</td>
    </tr>
    <tr>
        <td>2330</td>
        <td><a href=players.php?pid=67322&edition=5>cherbyss</a></td>
        <td>1</td>
        <td>9876.227</td>
        <td>717.000</td>
    </tr>
    <tr>
        <td>2331</td>
        <td><a href=players.php?pid=72587&edition=5>Monster2332</a></td>
        <td>1</td>
        <td>9876.227</td>
        <td>717.000</td>
    </tr>
    <tr>
        <td>2332</td>
        <td><a href=players.php?pid=6578&edition=5>isigold</a></td>
        <td>1</td>
        <td>9876.267</td>
        <td>720.000</td>
    </tr>
    <tr>
        <td>2333</td>
        <td><a href=players.php?pid=16864&edition=5>GamBear_US</a></td>
        <td>1</td>
        <td>9876.293</td>
        <td>722.000</td>
    </tr>
    <tr>
        <td>2334</td>
        <td><a href=players.php?pid=65650&edition=5>jackbumcheeks</a></td>
        <td>1</td>
        <td>9876.320</td>
        <td>724.000</td>
    </tr>
    <tr>
        <td>2335</td>
        <td><a href=players.php?pid=61302&edition=5>luther7.</a></td>
        <td>1</td>
        <td>9876.333</td>
        <td>725.000</td>
    </tr>
    <tr>
        <td>2336</td>
        <td><a href=players.php?pid=14627&edition=5>wolfpuppy.<span style='color:#ffccff;'>wav&nbsp;</span></a></td>
        <td>1</td>
        <td>9876.360</td>
        <td>727.000</td>
    </tr>
    <tr>
        <td>2337</td>
        <td><a href=players.php?pid=32434&edition=5>BagelBoyTM</a></td>
        <td>1</td>
        <td>9876.360</td>
        <td>727.000</td>
    </tr>
    <tr>
        <td>2338</td>
        <td><a href=players.php?pid=30269&edition=5>swivii</a></td>
        <td>1</td>
        <td>9876.467</td>
        <td>735.000</td>
    </tr>
    <tr>
        <td>2339</td>
        <td><a href=players.php?pid=70513&edition=5>WetBiscuitLUL</a></td>
        <td>1</td>
        <td>9876.467</td>
        <td>735.000</td>
    </tr>
    <tr>
        <td>2340</td>
        <td><a href=players.php?pid=6590&edition=5>VirusTM_</a></td>
        <td>1</td>
        <td>9876.480</td>
        <td>736.000</td>
    </tr>
    <tr>
        <td>2341</td>
        <td><a href=players.php?pid=45639&edition=5><span style='color:#cc0077;'></span><span
                    style='color:#aa5599;'>L</span><span style='color:#7777aa;'>L</span><span
                    style='color:#0099cc;'>✗</span></a></td>
        <td>1</td>
        <td>9876.480</td>
        <td>736.000</td>
    </tr>
    <tr>
        <td>2342</td>
        <td><a href=players.php?pid=31846&edition=5>Crristal-.-</a></td>
        <td>1</td>
        <td>9876.480</td>
        <td>736.000</td>
    </tr>
    <tr>
        <td>2343</td>
        <td><a href=players.php?pid=27&edition=5><span style='color:#00ffff;'>Đ</span><span
                    style='color:#11ffcc;'>ӧ</span><span style='color:#11ff99;'>ӧ</span><span
                    style='color:#22ff66;'>ท</span><span style='color:#22ff33;'>d</span><span
                    style='color:#33ff00;'>y</span></a></td>
        <td>1</td>
        <td>9876.493</td>
        <td>737.000</td>
    </tr>
    <tr>
        <td>2344</td>
        <td><a href=players.php?pid=66250&edition=5>Makrellen&nbsp;:3</a></td>
        <td>1</td>
        <td>9876.507</td>
        <td>738.000</td>
    </tr>
    <tr>
        <td>2345</td>
        <td><a href=players.php?pid=34088&edition=5>fivoo</a></td>
        <td>1</td>
        <td>9876.507</td>
        <td>738.000</td>
    </tr>
    <tr>
        <td>2346</td>
        <td><a href=players.php?pid=70588&edition=5>danjan17</a></td>
        <td>1</td>
        <td>9876.520</td>
        <td>739.000</td>
    </tr>
    <tr>
        <td>2347</td>
        <td><a href=players.php?pid=6676&edition=5>RedlineTM</a></td>
        <td>1</td>
        <td>9876.533</td>
        <td>740.000</td>
    </tr>
    <tr>
        <td>2348</td>
        <td><a href=players.php?pid=13511&edition=5>justCallMeEars</a></td>
        <td>1</td>
        <td>9876.560</td>
        <td>742.000</td>
    </tr>
    <tr>
        <td>2349</td>
        <td><a href=players.php?pid=49373&edition=5>lensdu</a></td>
        <td>1</td>
        <td>9876.560</td>
        <td>742.000</td>
    </tr>
    <tr>
        <td>2350</td>
        <td><a href=players.php?pid=72193&edition=5>MrTomahawxX</a></td>
        <td>1</td>
        <td>9876.560</td>
        <td>742.000</td>
    </tr>
    <tr>
        <td>2351</td>
        <td><a href=players.php?pid=50254&edition=5>Tomz.TM</a></td>
        <td>1</td>
        <td>9876.587</td>
        <td>744.000</td>
    </tr>
    <tr>
        <td>2352</td>
        <td><a href=players.php?pid=67131&edition=5>Neeckolah</a></td>
        <td>1</td>
        <td>9876.627</td>
        <td>747.000</td>
    </tr>
    <tr>
        <td>2353</td>
        <td><a href=players.php?pid=69263&edition=5>Ghost7463</a></td>
        <td>1</td>
        <td>9876.640</td>
        <td>748.000</td>
    </tr>
    <tr>
        <td>2354</td>
        <td><a href=players.php?pid=64302&edition=5>Maangi780</a></td>
        <td>1</td>
        <td>9876.667</td>
        <td>750.000</td>
    </tr>
    <tr>
        <td>2355</td>
        <td><a href=players.php?pid=267&edition=5>Walegen</a></td>
        <td>1</td>
        <td>9876.693</td>
        <td>752.000</td>
    </tr>
    <tr>
        <td>2356</td>
        <td><a href=players.php?pid=53065&edition=5>FG418</a></td>
        <td>1</td>
        <td>9876.693</td>
        <td>752.000</td>
    </tr>
    <tr>
        <td>2357</td>
        <td><a href=players.php?pid=65454&edition=5>axel9003</a></td>
        <td>1</td>
        <td>9876.707</td>
        <td>753.000</td>
    </tr>
    <tr>
        <td>2358</td>
        <td><a href=players.php?pid=66868&edition=5>HjalteHN</a></td>
        <td>1</td>
        <td>9876.720</td>
        <td>754.000</td>
    </tr>
    <tr>
        <td>2359</td>
        <td><a href=players.php?pid=54551&edition=5>Neezi.</a></td>
        <td>1</td>
        <td>9876.760</td>
        <td>757.000</td>
    </tr>
    <tr>
        <td>2360</td>
        <td><a href=players.php?pid=69479&edition=5>Kalzrocrynth</a></td>
        <td>1</td>
        <td>9876.800</td>
        <td>760.000</td>
    </tr>
    <tr>
        <td>2361</td>
        <td><a href=players.php?pid=52470&edition=5>FolliN1912</a></td>
        <td>1</td>
        <td>9876.853</td>
        <td>764.000</td>
    </tr>
    <tr>
        <td>2362</td>
        <td><a href=players.php?pid=31944&edition=5>nightmarathon.</a></td>
        <td>1</td>
        <td>9876.893</td>
        <td>767.000</td>
    </tr>
    <tr>
        <td>2363</td>
        <td><a href=players.php?pid=68429&edition=5>schnopszuzla</a></td>
        <td>1</td>
        <td>9876.907</td>
        <td>768.000</td>
    </tr>
    <tr>
        <td>2364</td>
        <td><a href=players.php?pid=58064&edition=5>SFShallow</a></td>
        <td>1</td>
        <td>9876.933</td>
        <td>770.000</td>
    </tr>
    <tr>
        <td>2365</td>
        <td><a href=players.php?pid=69581&edition=5>Golgattv</a></td>
        <td>1</td>
        <td>9876.933</td>
        <td>770.000</td>
    </tr>
    <tr>
        <td>2366</td>
        <td><a href=players.php?pid=53863&edition=5>VinexVX</a></td>
        <td>1</td>
        <td>9877.000</td>
        <td>775.000</td>
    </tr>
    <tr>
        <td>2367</td>
        <td><a href=players.php?pid=7600&edition=5>Otto_1221</a></td>
        <td>1</td>
        <td>9877.013</td>
        <td>776.000</td>
    </tr>
    <tr>
        <td>2368</td>
        <td><a href=players.php?pid=20032&edition=5>Fluffy_TM</a></td>
        <td>1</td>
        <td>9877.027</td>
        <td>777.000</td>
    </tr>
    <tr>
        <td>2369</td>
        <td><a href=players.php?pid=69057&edition=5>Koepsells_</a></td>
        <td>1</td>
        <td>9877.053</td>
        <td>779.000</td>
    </tr>
    <tr>
        <td>2370</td>
        <td><a href=players.php?pid=26031&edition=5>Simy_21</a></td>
        <td>1</td>
        <td>9877.080</td>
        <td>781.000</td>
    </tr>
    <tr>
        <td>2371</td>
        <td><a href=players.php?pid=53759&edition=5>BeanMachinee</a></td>
        <td>1</td>
        <td>9877.093</td>
        <td>782.000</td>
    </tr>
    <tr>
        <td>2372</td>
        <td><a href=players.php?pid=70337&edition=5>Coppa</a></td>
        <td>1</td>
        <td>9877.107</td>
        <td>783.000</td>
    </tr>
    <tr>
        <td>2373</td>
        <td><a href=players.php?pid=40734&edition=5>parasyte99</a></td>
        <td>1</td>
        <td>9877.147</td>
        <td>786.000</td>
    </tr>
    <tr>
        <td>2374</td>
        <td><a href=players.php?pid=69648&edition=5>DxT-Oxo</a></td>
        <td>1</td>
        <td>9877.213</td>
        <td>791.000</td>
    </tr>
    <tr>
        <td>2375</td>
        <td><a href=players.php?pid=63771&edition=5>YemixaM</a></td>
        <td>1</td>
        <td>9877.267</td>
        <td>795.000</td>
    </tr>
    <tr>
        <td>2376</td>
        <td><a href=players.php?pid=64274&edition=5>SpyPenguin99</a></td>
        <td>1</td>
        <td>9877.280</td>
        <td>796.000</td>
    </tr>
    <tr>
        <td>2377</td>
        <td><a href=players.php?pid=41825&edition=5>Donovanth1</a></td>
        <td>1</td>
        <td>9877.293</td>
        <td>797.000</td>
    </tr>
    <tr>
        <td>2378</td>
        <td><a href=players.php?pid=11202&edition=5>Carl.LL</a></td>
        <td>1</td>
        <td>9877.347</td>
        <td>801.000</td>
    </tr>
    <tr>
        <td>2379</td>
        <td><a href=players.php?pid=28443&edition=5>Myt4iq</a></td>
        <td>1</td>
        <td>9877.360</td>
        <td>802.000</td>
    </tr>
    <tr>
        <td>2380</td>
        <td><a href=players.php?pid=68991&edition=5>Dippzz_</a></td>
        <td>1</td>
        <td>9877.413</td>
        <td>806.000</td>
    </tr>
    <tr>
        <td>2381</td>
        <td><a href=players.php?pid=55698&edition=5>Spcterrr</a></td>
        <td>1</td>
        <td>9877.427</td>
        <td>807.000</td>
    </tr>
    <tr>
        <td>2382</td>
        <td><a href=players.php?pid=19137&edition=5><span style='color:#3366cc;'>X</span><span
                    style='color:#7799dd;'>y</span><span style='color:#bbccee;'>n</span><span
                    style='color:#ffffff;'>o</span><span style='color:#ffffff;'>_</span><span
                    style='color:#ff9988;'>T</span><span style='color:#ff3300;'>m</span></a></td>
        <td>1</td>
        <td>9877.440</td>
        <td>808.000</td>
    </tr>
    <tr>
        <td>2383</td>
        <td><a href=players.php?pid=27094&edition=5>chunkycheese</a></td>
        <td>1</td>
        <td>9877.480</td>
        <td>811.000</td>
    </tr>
    <tr>
        <td>2384</td>
        <td><a href=players.php?pid=21172&edition=5>Levelfailer</a></td>
        <td>1</td>
        <td>9877.573</td>
        <td>818.000</td>
    </tr>
    <tr>
        <td>2385</td>
        <td><a href=players.php?pid=68271&edition=5>Skoppette</a></td>
        <td>1</td>
        <td>9877.587</td>
        <td>819.000</td>
    </tr>
    <tr>
        <td>2386</td>
        <td><a href=players.php?pid=8097&edition=5>BLxxKOUT</a></td>
        <td>1</td>
        <td>9877.667</td>
        <td>825.000</td>
    </tr>
    <tr>
        <td>2387</td>
        <td><a href=players.php?pid=8312&edition=5>tjoeming</a></td>
        <td>1</td>
        <td>9877.693</td>
        <td>827.000</td>
    </tr>
    <tr>
        <td>2388</td>
        <td><a href=players.php?pid=66139&edition=5><span style='color:#332211;'>T</span><span
                    style='color:#553322;'>E</span><span style='color:#553322;'>D</span><span
                    style='color:#664433;'>D</span><span style='color:#aa7766;'>Y</span></a></td>
        <td>1</td>
        <td>9877.720</td>
        <td>829.000</td>
    </tr>
    <tr>
        <td>2389</td>
        <td><a href=players.php?pid=19911&edition=5>Andybaguette</a></td>
        <td>1</td>
        <td>9877.733</td>
        <td>830.000</td>
    </tr>
    <tr>
        <td>2390</td>
        <td><a href=players.php?pid=37682&edition=5>Xzam_</a></td>
        <td>1</td>
        <td>9877.800</td>
        <td>835.000</td>
    </tr>
    <tr>
        <td>2391</td>
        <td><a href=players.php?pid=71439&edition=5>MC_Shxdowz</a></td>
        <td>1</td>
        <td>9877.813</td>
        <td>836.000</td>
    </tr>
    <tr>
        <td>2392</td>
        <td><a href=players.php?pid=66976&edition=5><span style='color:#00ffff;'>cyan</span></a></td>
        <td>1</td>
        <td>9877.827</td>
        <td>837.000</td>
    </tr>
    <tr>
        <td>2393</td>
        <td><a href=players.php?pid=67861&edition=5>truliqq</a></td>
        <td>1</td>
        <td>9877.840</td>
        <td>838.000</td>
    </tr>
    <tr>
        <td>2394</td>
        <td><a href=players.php?pid=41093&edition=5>PekoIsDaMaster</a></td>
        <td>1</td>
        <td>9877.880</td>
        <td>841.000</td>
    </tr>
    <tr>
        <td>2395</td>
        <td><a href=players.php?pid=70442&edition=5>oyutsaki</a></td>
        <td>1</td>
        <td>9877.893</td>
        <td>842.000</td>
    </tr>
    <tr>
        <td>2396</td>
        <td><a href=players.php?pid=52139&edition=5>sqett</a></td>
        <td>1</td>
        <td>9877.893</td>
        <td>842.000</td>
    </tr>
    <tr>
        <td>2397</td>
        <td><a href=players.php?pid=66973&edition=5>Syndrave</a></td>
        <td>1</td>
        <td>9877.907</td>
        <td>843.000</td>
    </tr>
    <tr>
        <td>2398</td>
        <td><a href=players.php?pid=66794&edition=5>Luchl_</a></td>
        <td>1</td>
        <td>9877.920</td>
        <td>844.000</td>
    </tr>
    <tr>
        <td>2399</td>
        <td><a href=players.php?pid=61954&edition=5><span style='color:#ff0000;'>ャ</span><span
                    style='color:#ff2200;'>&epsilon;</span><span style='color:#ff4400;'>я</span><span
                    style='color:#ff6600;'>ę</span><span style='color:#ff9900;'>&tau;</span><span
                    style='color:#ffbb00;'>ŗ</span><span style='color:#ffdd00;'>&otilde;</span><span
                    style='color:#ffff00;'>й</span></a></td>
        <td>1</td>
        <td>9877.947</td>
        <td>846.000</td>
    </tr>
    <tr>
        <td>2400</td>
        <td><a href=players.php?pid=30189&edition=5>Ergitta</a></td>
        <td>1</td>
        <td>9878.000</td>
        <td>850.000</td>
    </tr>
    <tr>
        <td>2401</td>
        <td><a href=players.php?pid=69827&edition=5>Oni_TM</a></td>
        <td>1</td>
        <td>9878.027</td>
        <td>852.000</td>
    </tr>
    <tr>
        <td>2402</td>
        <td><a href=players.php?pid=24936&edition=5>ASMRoshie</a></td>
        <td>1</td>
        <td>9878.040</td>
        <td>853.000</td>
    </tr>
    <tr>
        <td>2403</td>
        <td><a href=players.php?pid=4514&edition=5>TheRavus</a></td>
        <td>1</td>
        <td>9878.080</td>
        <td>856.000</td>
    </tr>
    <tr>
        <td>2404</td>
        <td><a href=players.php?pid=68980&edition=5>MatiiMarfi</a></td>
        <td>1</td>
        <td>9878.107</td>
        <td>858.000</td>
    </tr>
    <tr>
        <td>2405</td>
        <td><a href=players.php?pid=23045&edition=5><span style='color:#9900cc;'>A</span><span
                    style='color:#8800bb;'>dn</span><span style='color:#7700aa;'>i</span><span
                    style='color:#660099;'>b</span><span style='color:#660099;'>h</span><span
                    style='color:#770099;'>a</span><span style='color:#880099;'>a</span><span
                    style='color:#990099;'>l</span></a></td>
        <td>1</td>
        <td>9878.107</td>
        <td>858.000</td>
    </tr>
    <tr>
        <td>2406</td>
        <td><a href=players.php?pid=7951&edition=5>Ymqbawb</a></td>
        <td>1</td>
        <td>9878.120</td>
        <td>859.000</td>
    </tr>
    <tr>
        <td>2407</td>
        <td><a href=players.php?pid=69299&edition=5>B1998w31Ga</a></td>
        <td>1</td>
        <td>9878.173</td>
        <td>863.000</td>
    </tr>
    <tr>
        <td>2408</td>
        <td><a href=players.php?pid=19327&edition=5>Markus_MT</a></td>
        <td>1</td>
        <td>9878.187</td>
        <td>864.000</td>
    </tr>
    <tr>
        <td>2409</td>
        <td><a href=players.php?pid=68213&edition=5>Hassonfam</a></td>
        <td>1</td>
        <td>9878.200</td>
        <td>865.000</td>
    </tr>
    <tr>
        <td>2410</td>
        <td><a href=players.php?pid=45499&edition=5>Willi_LutTM</a></td>
        <td>1</td>
        <td>9878.213</td>
        <td>866.000</td>
    </tr>
    <tr>
        <td>2411</td>
        <td><a href=players.php?pid=59545&edition=5>TI64CLi</a></td>
        <td>1</td>
        <td>9878.213</td>
        <td>866.000</td>
    </tr>
    <tr>
        <td>2412</td>
        <td><a href=players.php?pid=50936&edition=5>gavatron11</a></td>
        <td>1</td>
        <td>9878.253</td>
        <td>869.000</td>
    </tr>
    <tr>
        <td>2413</td>
        <td><a href=players.php?pid=69324&edition=5>Matteo64_</a></td>
        <td>1</td>
        <td>9878.267</td>
        <td>870.000</td>
    </tr>
    <tr>
        <td>2414</td>
        <td><a href=players.php?pid=44780&edition=5>Slime_BoB_</a></td>
        <td>1</td>
        <td>9878.307</td>
        <td>873.000</td>
    </tr>
    <tr>
        <td>2415</td>
        <td><a href=players.php?pid=54161&edition=5>woulfzy</a></td>
        <td>1</td>
        <td>9878.333</td>
        <td>875.000</td>
    </tr>
    <tr>
        <td>2416</td>
        <td><a href=players.php?pid=31539&edition=5>JohnnyCashCash</a></td>
        <td>1</td>
        <td>9878.347</td>
        <td>876.000</td>
    </tr>
    <tr>
        <td>2417</td>
        <td><a href=players.php?pid=37023&edition=5>ThropDead</a></td>
        <td>1</td>
        <td>9878.427</td>
        <td>882.000</td>
    </tr>
    <tr>
        <td>2418</td>
        <td><a href=players.php?pid=45971&edition=5>Flakkes</a></td>
        <td>1</td>
        <td>9878.427</td>
        <td>882.000</td>
    </tr>
    <tr>
        <td>2419</td>
        <td><a href=players.php?pid=69850&edition=5>elr_rojo</a></td>
        <td>1</td>
        <td>9878.440</td>
        <td>883.000</td>
    </tr>
    <tr>
        <td>2420</td>
        <td><a href=players.php?pid=24031&edition=5>Feliasson</a></td>
        <td>1</td>
        <td>9878.480</td>
        <td>886.000</td>
    </tr>
    <tr>
        <td>2421</td>
        <td><a href=players.php?pid=42150&edition=5>Twenty3TM</a></td>
        <td>1</td>
        <td>9878.573</td>
        <td>893.000</td>
    </tr>
    <tr>
        <td>2422</td>
        <td><a href=players.php?pid=66365&edition=5>Bonifax99</a></td>
        <td>1</td>
        <td>9878.600</td>
        <td>895.000</td>
    </tr>
    <tr>
        <td>2423</td>
        <td><a href=players.php?pid=21235&edition=5>Fordsy-YT-</a></td>
        <td>1</td>
        <td>9878.667</td>
        <td>900.000</td>
    </tr>
    <tr>
        <td>2424</td>
        <td><a href=players.php?pid=66580&edition=5>Floflo56500</a></td>
        <td>1</td>
        <td>9878.720</td>
        <td>904.000</td>
    </tr>
    <tr>
        <td>2425</td>
        <td><a href=players.php?pid=61734&edition=5>Grimwo</a></td>
        <td>1</td>
        <td>9878.773</td>
        <td>908.000</td>
    </tr>
    <tr>
        <td>2426</td>
        <td><a href=players.php?pid=33292&edition=5>Delta_Mage</a></td>
        <td>1</td>
        <td>9878.800</td>
        <td>910.000</td>
    </tr>
    <tr>
        <td>2427</td>
        <td><a href=players.php?pid=4485&edition=5>SiiDZeR</a></td>
        <td>1</td>
        <td>9878.853</td>
        <td>914.000</td>
    </tr>
    <tr>
        <td>2428</td>
        <td><a href=players.php?pid=24847&edition=5>CariQ_TM</a></td>
        <td>1</td>
        <td>9878.853</td>
        <td>914.000</td>
    </tr>
    <tr>
        <td>2429</td>
        <td><a href=players.php?pid=5240&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;Korol</span></a></td>
        <td>1</td>
        <td>9878.880</td>
        <td>916.000</td>
    </tr>
    <tr>
        <td>2430</td>
        <td><a href=players.php?pid=67363&edition=5>LTBR00</a></td>
        <td>1</td>
        <td>9878.933</td>
        <td>920.000</td>
    </tr>
    <tr>
        <td>2431</td>
        <td><a href=players.php?pid=65474&edition=5>LeinAdmiral</a></td>
        <td>1</td>
        <td>9878.947</td>
        <td>921.000</td>
    </tr>
    <tr>
        <td>2432</td>
        <td><a href=players.php?pid=59384&edition=5>Modeus59</a></td>
        <td>1</td>
        <td>9879.000</td>
        <td>925.000</td>
    </tr>
    <tr>
        <td>2433</td>
        <td><a href=players.php?pid=71844&edition=5>KickScope</a></td>
        <td>1</td>
        <td>9879.013</td>
        <td>926.000</td>
    </tr>
    <tr>
        <td>2434</td>
        <td><a href=players.php?pid=57123&edition=5>Dimoneuclidea</a></td>
        <td>1</td>
        <td>9879.120</td>
        <td>934.000</td>
    </tr>
    <tr>
        <td>2435</td>
        <td><a href=players.php?pid=12849&edition=5>sunhomeTM</a></td>
        <td>1</td>
        <td>9879.147</td>
        <td>936.000</td>
    </tr>
    <tr>
        <td>2436</td>
        <td><a href=players.php?pid=70150&edition=5>RDG-27</a></td>
        <td>1</td>
        <td>9879.200</td>
        <td>940.000</td>
    </tr>
    <tr>
        <td>2437</td>
        <td><a href=players.php?pid=20929&edition=5><span style='color:#ff6633;'>M</span><span
                    style='color:#ee6633;'>a</span><span style='color:#dd6633;'>i</span><span
                    style='color:#cc6633;'>s</span><span style='color:#cc6633;'>u</span><span
                    style='color:#884422;'>J</span><span style='color:#442211;'>a</span><span
                    style='color:#000000;'>y</span></a></td>
        <td>1</td>
        <td>9879.240</td>
        <td>943.000</td>
    </tr>
    <tr>
        <td>2438</td>
        <td><a href=players.php?pid=71203&edition=5>EducatedNoob</a></td>
        <td>1</td>
        <td>9879.267</td>
        <td>945.000</td>
    </tr>
    <tr>
        <td>2439</td>
        <td><a href=players.php?pid=69302&edition=5>poundsignMVP</a></td>
        <td>1</td>
        <td>9879.293</td>
        <td>947.000</td>
    </tr>
    <tr>
        <td>2440</td>
        <td><a href=players.php?pid=18995&edition=5>Niama_35</a></td>
        <td>1</td>
        <td>9879.307</td>
        <td>948.000</td>
    </tr>
    <tr>
        <td>2441</td>
        <td><a href=players.php?pid=67468&edition=5><span style='color:#ffffff;'>Jaksuhn.</span><span
                    style='color:#ccccff;'>K</span><span style='color:#ccccff;'>a</span><span
                    style='color:#bbbbff;'>c</span><span style='color:#bb99ff;'>c</span><span
                    style='color:#aa88ff;'>h</span><span style='color:#9966ff;'>i</span></a></td>
        <td>1</td>
        <td>9879.427</td>
        <td>957.000</td>
    </tr>
    <tr>
        <td>2442</td>
        <td><a href=players.php?pid=52179&edition=5>Takina-Sama</a></td>
        <td>1</td>
        <td>9879.453</td>
        <td>959.000</td>
    </tr>
    <tr>
        <td>2443</td>
        <td><a href=players.php?pid=46429&edition=5>RedTiger1510</a></td>
        <td>1</td>
        <td>9879.480</td>
        <td>961.000</td>
    </tr>
    <tr>
        <td>2444</td>
        <td><a href=players.php?pid=40418&edition=5>sin_incarnate</a></td>
        <td>1</td>
        <td>9879.520</td>
        <td>964.000</td>
    </tr>
    <tr>
        <td>2445</td>
        <td><a href=players.php?pid=30072&edition=5>wrcup</a></td>
        <td>1</td>
        <td>9879.573</td>
        <td>968.000</td>
    </tr>
    <tr>
        <td>2446</td>
        <td><a href=players.php?pid=69838&edition=5>PDTS-Noraus</a></td>
        <td>1</td>
        <td>9879.587</td>
        <td>969.000</td>
    </tr>
    <tr>
        <td>2447</td>
        <td><a href=players.php?pid=52591&edition=5>YXxACExXY</a></td>
        <td>1</td>
        <td>9879.627</td>
        <td>972.000</td>
    </tr>
    <tr>
        <td>2448</td>
        <td><a href=players.php?pid=1715&edition=5>molvansnoa</a></td>
        <td>1</td>
        <td>9879.667</td>
        <td>975.000</td>
    </tr>
    <tr>
        <td>2449</td>
        <td><a href=players.php?pid=34122&edition=5>Bludi01</a></td>
        <td>1</td>
        <td>9879.680</td>
        <td>976.000</td>
    </tr>
    <tr>
        <td>2450</td>
        <td><a href=players.php?pid=39622&edition=5>Caucau-10</a></td>
        <td>1</td>
        <td>9879.707</td>
        <td>978.000</td>
    </tr>
    <tr>
        <td>2451</td>
        <td><a href=players.php?pid=62050&edition=5>underyx</a></td>
        <td>1</td>
        <td>9879.853</td>
        <td>989.000</td>
    </tr>
    <tr>
        <td>2452</td>
        <td><a href=players.php?pid=47005&edition=5>Slowkingng</a></td>
        <td>1</td>
        <td>9879.867</td>
        <td>990.000</td>
    </tr>
    <tr>
        <td>2453</td>
        <td><a href=players.php?pid=68004&edition=5>Aragier</a></td>
        <td>1</td>
        <td>9879.867</td>
        <td>990.000</td>
    </tr>
    <tr>
        <td>2454</td>
        <td><a href=players.php?pid=66983&edition=5>LiterallyWayne</a></td>
        <td>1</td>
        <td>9879.893</td>
        <td>992.000</td>
    </tr>
    <tr>
        <td>2455</td>
        <td><a href=players.php?pid=25323&edition=5>robin_bouma</a></td>
        <td>1</td>
        <td>9879.933</td>
        <td>995.000</td>
    </tr>
    <tr>
        <td>2456</td>
        <td><a href=players.php?pid=68123&edition=5>charliew1141</a></td>
        <td>1</td>
        <td>9880.000</td>
        <td>1000.000</td>
    </tr>
    <tr>
        <td>2457</td>
        <td><a href=players.php?pid=21545&edition=5>Khamul30</a></td>
        <td>1</td>
        <td>9880.120</td>
        <td>1009.000</td>
    </tr>
    <tr>
        <td>2458</td>
        <td><a href=players.php?pid=1302&edition=5>Moxx_96</a></td>
        <td>1</td>
        <td>9880.240</td>
        <td>1018.000</td>
    </tr>
    <tr>
        <td>2459</td>
        <td><a href=players.php?pid=69392&edition=5>N0NB0B</a></td>
        <td>1</td>
        <td>9880.280</td>
        <td>1021.000</td>
    </tr>
    <tr>
        <td>2460</td>
        <td><a href=players.php?pid=72549&edition=5>Rexauros</a></td>
        <td>1</td>
        <td>9880.280</td>
        <td>1021.000</td>
    </tr>
    <tr>
        <td>2461</td>
        <td><a href=players.php?pid=13722&edition=5>Ooooolaw</a></td>
        <td>1</td>
        <td>9880.413</td>
        <td>1031.000</td>
    </tr>
    <tr>
        <td>2462</td>
        <td><a href=players.php?pid=21859&edition=5>NotZeKo</a></td>
        <td>1</td>
        <td>9880.427</td>
        <td>1032.000</td>
    </tr>
    <tr>
        <td>2463</td>
        <td><a href=players.php?pid=67385&edition=5>Bignuses</a></td>
        <td>1</td>
        <td>9880.427</td>
        <td>1032.000</td>
    </tr>
    <tr>
        <td>2464</td>
        <td><a href=players.php?pid=64312&edition=5>blokhoved_TM</a></td>
        <td>1</td>
        <td>9880.440</td>
        <td>1033.000</td>
    </tr>
    <tr>
        <td>2465</td>
        <td><a href=players.php?pid=71658&edition=5>HAIZA.</a></td>
        <td>1</td>
        <td>9880.480</td>
        <td>1036.000</td>
    </tr>
    <tr>
        <td>2466</td>
        <td><a href=players.php?pid=53878&edition=5>Eleven11XI</a></td>
        <td>1</td>
        <td>9880.520</td>
        <td>1039.000</td>
    </tr>
    <tr>
        <td>2467</td>
        <td><a href=players.php?pid=54821&edition=5>dnt_pnc</a></td>
        <td>1</td>
        <td>9880.533</td>
        <td>1040.000</td>
    </tr>
    <tr>
        <td>2468</td>
        <td><a href=players.php?pid=10972&edition=5>ImatankMH</a></td>
        <td>1</td>
        <td>9880.587</td>
        <td>1044.000</td>
    </tr>
    <tr>
        <td>2469</td>
        <td><a href=players.php?pid=300&edition=5>Astropodess</a></td>
        <td>1</td>
        <td>9880.600</td>
        <td>1045.000</td>
    </tr>
    <tr>
        <td>2470</td>
        <td><a href=players.php?pid=69251&edition=5>latenightskyes</a></td>
        <td>1</td>
        <td>9880.640</td>
        <td>1048.000</td>
    </tr>
    <tr>
        <td>2471</td>
        <td><a href=players.php?pid=47357&edition=5>Frundelbune</a></td>
        <td>1</td>
        <td>9880.693</td>
        <td>1052.000</td>
    </tr>
    <tr>
        <td>2472</td>
        <td><a href=players.php?pid=39381&edition=5>ShinyRuby</a></td>
        <td>1</td>
        <td>9880.693</td>
        <td>1052.000</td>
    </tr>
    <tr>
        <td>2473</td>
        <td><a href=players.php?pid=50608&edition=5>xkingDiV</a></td>
        <td>1</td>
        <td>9880.747</td>
        <td>1056.000</td>
    </tr>
    <tr>
        <td>2474</td>
        <td><a href=players.php?pid=33173&edition=5>Lycoris.TM</a></td>
        <td>1</td>
        <td>9880.760</td>
        <td>1057.000</td>
    </tr>
    <tr>
        <td>2475</td>
        <td><a href=players.php?pid=65963&edition=5>Eastor1no</a></td>
        <td>1</td>
        <td>9880.760</td>
        <td>1057.000</td>
    </tr>
    <tr>
        <td>2476</td>
        <td><a href=players.php?pid=45634&edition=5><span style='color:#ff9900;'>O</span><span
                    style='color:#ee8822;'>b</span><span style='color:#dd7744;'>l</span><span
                    style='color:#cc6666;'>i</span><span style='color:#cc6666;'>v</span><span
                    style='color:#bb4488;'>i</span><span style='color:#aa22aa;'>o</span><span
                    style='color:#9900cc;'>n&nbsp;:smirkcat:</span></a></td>
        <td>1</td>
        <td>9880.853</td>
        <td>1064.000</td>
    </tr>
    <tr>
        <td>2477</td>
        <td><a href=players.php?pid=63329&edition=5><span
                    style='color:#ff6600;font-style:italic;font-weight:bold;'>Th</span><span
                    style='color:#ff5500;font-style:italic;font-weight:bold;'>ri</span><span
                    style='color:#ee5500;font-style:italic;font-weight:bold;'>v</span><span
                    style='color:#ee4400;font-style:italic;font-weight:bold;'>el</span><span
                    style='color:#ee3300;font-style:italic;font-weight:bold;'>lo</span><span
                    style='font-weight:bold;'>.</span><span style='color:#555555;font-weight:bold;'>O</span><span
                    style='color:#333333;font-weight:bold;'>w</span><span
                    style='color:#555555;font-weight:bold;'>O</span></a></td>
        <td>1</td>
        <td>9880.893</td>
        <td>1067.000</td>
    </tr>
    <tr>
        <td>2478</td>
        <td><a href=players.php?pid=65378&edition=5>fabian123100</a></td>
        <td>1</td>
        <td>9880.920</td>
        <td>1069.000</td>
    </tr>
    <tr>
        <td>2479</td>
        <td><a href=players.php?pid=66226&edition=5><span style='color:#ffcc66;'>H</span><span
                    style='color:#ffcc77;'>⏳</span><span style='color:#ffdd88;'>H&nbsp;</span><span
                    style='color:#ffdd99;'>R</span><span style='color:#ffddaa;'>a</span><span
                    style='color:#ffeebb;'>nd</span><span style='color:#ffeecc;'>o</span><span
                    style='color:#ffeedd;'>r</span><span style='color:#ffffee;'>rr</span><span
                    style='color:#ffffff;'>r</span></a></td>
        <td>1</td>
        <td>9881.093</td>
        <td>1082.000</td>
    </tr>
    <tr>
        <td>2480</td>
        <td><a href=players.php?pid=63060&edition=5>a_15septemper</a></td>
        <td>1</td>
        <td>9881.120</td>
        <td>1084.000</td>
    </tr>
    <tr>
        <td>2481</td>
        <td><a href=players.php?pid=70425&edition=5>Sahrah_Shikhuh</a></td>
        <td>1</td>
        <td>9881.160</td>
        <td>1087.000</td>
    </tr>
    <tr>
        <td>2482</td>
        <td><a href=players.php?pid=70321&edition=5>IJaycealot</a></td>
        <td>1</td>
        <td>9881.253</td>
        <td>1094.000</td>
    </tr>
    <tr>
        <td>2483</td>
        <td><a href=players.php?pid=69897&edition=5><span style='color:#ff8800;font-weight:bold;'>Ge</span><span
                    style='color:#ff9900;font-weight:bold;'>rr</span><span
                    style='color:#ffaa00;font-weight:bold;'>ie</span><span
                    style='color:#ffbb00;font-weight:bold;'>Na</span><span
                    style='color:#ffcc00;font-weight:bold;'>to</span><span
                    style='color:#ffcc11;font-weight:bold;'>r</span></a></td>
        <td>1</td>
        <td>9881.293</td>
        <td>1097.000</td>
    </tr>
    <tr>
        <td>2484</td>
        <td><a href=players.php?pid=3143&edition=5>Carry_Moi</a></td>
        <td>1</td>
        <td>9881.333</td>
        <td>1100.000</td>
    </tr>
    <tr>
        <td>2485</td>
        <td><a href=players.php?pid=56072&edition=5>AylaKitty</a></td>
        <td>1</td>
        <td>9881.347</td>
        <td>1101.000</td>
    </tr>
    <tr>
        <td>2486</td>
        <td><a href=players.php?pid=6229&edition=5><span style='color:#000033;'>C</span><span
                    style='color:#114455;'>h</span><span style='color:#228877;'>a</span><span
                    style='color:#33cc99;'>u</span><span style='color:#33cc99;'>k</span><span
                    style='color:#2299cc;'>i</span><span style='color:#0066ff;'>i</span></a></td>
        <td>1</td>
        <td>9881.360</td>
        <td>1102.000</td>
    </tr>
    <tr>
        <td>2487</td>
        <td><a href=players.php?pid=68286&edition=5>ninzwzwz</a></td>
        <td>1</td>
        <td>9881.387</td>
        <td>1104.000</td>
    </tr>
    <tr>
        <td>2488</td>
        <td><a href=players.php?pid=64065&edition=5>Kares8911</a></td>
        <td>1</td>
        <td>9881.413</td>
        <td>1106.000</td>
    </tr>
    <tr>
        <td>2489</td>
        <td><a href=players.php?pid=35312&edition=5>Volcaine777</a></td>
        <td>1</td>
        <td>9881.493</td>
        <td>1112.000</td>
    </tr>
    <tr>
        <td>2490</td>
        <td><a href=players.php?pid=33624&edition=5><span style='color:#ff0000;'>C</span><span
                    style='color:#ff2200;'>u</span><span style='color:#ff3300;'>s</span><span
                    style='color:#ff5500;'>t</span><span style='color:#ff7700;'>o</span><span
                    style='color:#ff8800;'>m</span><span style='color:#ffaa00;'>P</span><span
                    style='color:#ffcc00;'>l</span><span style='color:#ffdd00;'>a</span><span
                    style='color:#ffff00;'>y</span></a></td>
        <td>1</td>
        <td>9881.520</td>
        <td>1114.000</td>
    </tr>
    <tr>
        <td>2491</td>
        <td><a href=players.php?pid=12875&edition=5><span style='color:#660000;'>Cap</span><span
                    style='color:#ffff00;'>tan</span></a></td>
        <td>1</td>
        <td>9881.573</td>
        <td>1118.000</td>
    </tr>
    <tr>
        <td>2492</td>
        <td><a href=players.php?pid=48383&edition=5>ArRokZ</a></td>
        <td>1</td>
        <td>9881.627</td>
        <td>1122.000</td>
    </tr>
    <tr>
        <td>2493</td>
        <td><a href=players.php?pid=47923&edition=5>Patte123776</a></td>
        <td>1</td>
        <td>9881.640</td>
        <td>1123.000</td>
    </tr>
    <tr>
        <td>2494</td>
        <td><a href=players.php?pid=70444&edition=5><span style='color:#ff00ff;'>M</span><span
                    style='color:#dd44ff;'>e</span><span style='color:#bb88ff;'>o</span><span
                    style='color:#88bbff;'>w</span><span style='color:#66ffff;'>z</span><span
                    style='color:#66ffff;'>y</span><span style='color:#99ffaa;'>.</span><span
                    style='color:#ccff55;'>T</span><span style='color:#ffff00;'>M</span></a></td>
        <td>1</td>
        <td>9881.760</td>
        <td>1132.000</td>
    </tr>
    <tr>
        <td>2495</td>
        <td><a href=players.php?pid=65370&edition=5>ShortViKingTM</a></td>
        <td>1</td>
        <td>9881.800</td>
        <td>1135.000</td>
    </tr>
    <tr>
        <td>2496</td>
        <td><a href=players.php?pid=70772&edition=5>zH.CarboN</a></td>
        <td>1</td>
        <td>9881.840</td>
        <td>1138.000</td>
    </tr>
    <tr>
        <td>2497</td>
        <td><a href=players.php?pid=65881&edition=5>alecvr17</a></td>
        <td>1</td>
        <td>9881.867</td>
        <td>1140.000</td>
    </tr>
    <tr>
        <td>2498</td>
        <td><a href=players.php?pid=52729&edition=5>HikoTM</a></td>
        <td>1</td>
        <td>9881.893</td>
        <td>1142.000</td>
    </tr>
    <tr>
        <td>2499</td>
        <td><a href=players.php?pid=43127&edition=5>Flumming...</a></td>
        <td>1</td>
        <td>9881.907</td>
        <td>1143.000</td>
    </tr>
    <tr>
        <td>2500</td>
        <td><a href=players.php?pid=60972&edition=5>zy56k</a></td>
        <td>1</td>
        <td>9881.933</td>
        <td>1145.000</td>
    </tr>
    <tr>
        <td>2501</td>
        <td><a href=players.php?pid=66772&edition=5>certifiedchump</a></td>
        <td>1</td>
        <td>9881.947</td>
        <td>1146.000</td>
    </tr>
    <tr>
        <td>2502</td>
        <td><a href=players.php?pid=69321&edition=5>C4YEETer.BoRiNG</a></td>
        <td>1</td>
        <td>9881.987</td>
        <td>1149.000</td>
    </tr>
    <tr>
        <td>2503</td>
        <td><a href=players.php?pid=32780&edition=5>herihel</a></td>
        <td>1</td>
        <td>9882.013</td>
        <td>1151.000</td>
    </tr>
    <tr>
        <td>2504</td>
        <td><a href=players.php?pid=6611&edition=5>BaneBoyTM</a></td>
        <td>1</td>
        <td>9882.013</td>
        <td>1151.000</td>
    </tr>
    <tr>
        <td>2505</td>
        <td><a href=players.php?pid=50469&edition=5>Jrich96</a></td>
        <td>1</td>
        <td>9882.027</td>
        <td>1152.000</td>
    </tr>
    <tr>
        <td>2506</td>
        <td><a href=players.php?pid=66257&edition=5>GraveFable</a></td>
        <td>1</td>
        <td>9882.040</td>
        <td>1153.000</td>
    </tr>
    <tr>
        <td>2507</td>
        <td><a href=players.php?pid=37477&edition=5>sand6136</a></td>
        <td>1</td>
        <td>9882.067</td>
        <td>1155.000</td>
    </tr>
    <tr>
        <td>2508</td>
        <td><a href=players.php?pid=29450&edition=5>SirKioi</a></td>
        <td>1</td>
        <td>9882.093</td>
        <td>1157.000</td>
    </tr>
    <tr>
        <td>2509</td>
        <td><a href=players.php?pid=38963&edition=5>xdd|&nbsp;<span style='color:#00ffcc;'>P</span><span
                    style='color:#003399;'>K</span></a></td>
        <td>1</td>
        <td>9882.107</td>
        <td>1158.000</td>
    </tr>
    <tr>
        <td>2510</td>
        <td><a href=players.php?pid=63315&edition=5>ping_wyn</a></td>
        <td>1</td>
        <td>9882.147</td>
        <td>1161.000</td>
    </tr>
    <tr>
        <td>2511</td>
        <td><a href=players.php?pid=24928&edition=5>Boivien</a></td>
        <td>1</td>
        <td>9882.147</td>
        <td>1161.000</td>
    </tr>
    <tr>
        <td>2512</td>
        <td><a href=players.php?pid=69157&edition=5>davep3004</a></td>
        <td>1</td>
        <td>9882.160</td>
        <td>1162.000</td>
    </tr>
    <tr>
        <td>2513</td>
        <td><a href=players.php?pid=66362&edition=5>Krunse</a></td>
        <td>1</td>
        <td>9882.173</td>
        <td>1163.000</td>
    </tr>
    <tr>
        <td>2514</td>
        <td><a href=players.php?pid=28430&edition=5>HITO.ToString</a></td>
        <td>1</td>
        <td>9882.200</td>
        <td>1165.000</td>
    </tr>
    <tr>
        <td>2515</td>
        <td><a href=players.php?pid=1766&edition=5>Schwaengu</a></td>
        <td>1</td>
        <td>9882.200</td>
        <td>1165.000</td>
    </tr>
    <tr>
        <td>2516</td>
        <td><a href=players.php?pid=71527&edition=5>Lookaah.</a></td>
        <td>1</td>
        <td>9882.240</td>
        <td>1168.000</td>
    </tr>
    <tr>
        <td>2517</td>
        <td><a href=players.php?pid=70151&edition=5>Kuwabara-kun</a></td>
        <td>1</td>
        <td>9882.253</td>
        <td>1169.000</td>
    </tr>
    <tr>
        <td>2518</td>
        <td><a href=players.php?pid=39715&edition=5>Pyro_TM</a></td>
        <td>1</td>
        <td>9882.307</td>
        <td>1173.000</td>
    </tr>
    <tr>
        <td>2519</td>
        <td><a href=players.php?pid=53703&edition=5>Kantareller</a></td>
        <td>1</td>
        <td>9882.373</td>
        <td>1178.000</td>
    </tr>
    <tr>
        <td>2520</td>
        <td><a href=players.php?pid=53711&edition=5>Zarellik</a></td>
        <td>1</td>
        <td>9882.400</td>
        <td>1180.000</td>
    </tr>
    <tr>
        <td>2521</td>
        <td><a href=players.php?pid=70889&edition=5>Vyrion_Nauta</a></td>
        <td>1</td>
        <td>9882.453</td>
        <td>1184.000</td>
    </tr>
    <tr>
        <td>2522</td>
        <td><a href=players.php?pid=50436&edition=5>xennTM</a></td>
        <td>1</td>
        <td>9882.493</td>
        <td>1187.000</td>
    </tr>
    <tr>
        <td>2523</td>
        <td><a href=players.php?pid=56303&edition=5>BRIM_TM</a></td>
        <td>1</td>
        <td>9882.547</td>
        <td>1191.000</td>
    </tr>
    <tr>
        <td>2524</td>
        <td><a href=players.php?pid=34176&edition=5>ShelbongCooper</a></td>
        <td>1</td>
        <td>9882.547</td>
        <td>1191.000</td>
    </tr>
    <tr>
        <td>2525</td>
        <td><a href=players.php?pid=41214&edition=5>Ham.tm</a></td>
        <td>1</td>
        <td>9882.627</td>
        <td>1197.000</td>
    </tr>
    <tr>
        <td>2526</td>
        <td><a href=players.php?pid=34019&edition=5>BC_The7Assassin</a></td>
        <td>1</td>
        <td>9882.653</td>
        <td>1199.000</td>
    </tr>
    <tr>
        <td>2527</td>
        <td><a href=players.php?pid=71083&edition=5>JaskullTV</a></td>
        <td>1</td>
        <td>9882.680</td>
        <td>1201.000</td>
    </tr>
    <tr>
        <td>2528</td>
        <td><a href=players.php?pid=66185&edition=5>remota.exe</a></td>
        <td>1</td>
        <td>9882.733</td>
        <td>1205.000</td>
    </tr>
    <tr>
        <td>2529</td>
        <td><a href=players.php?pid=68110&edition=5>LindereN</a></td>
        <td>1</td>
        <td>9882.760</td>
        <td>1207.000</td>
    </tr>
    <tr>
        <td>2530</td>
        <td><a href=players.php?pid=2909&edition=5>Baevern</a></td>
        <td>1</td>
        <td>9882.827</td>
        <td>1212.000</td>
    </tr>
    <tr>
        <td>2531</td>
        <td><a href=players.php?pid=71352&edition=5>Cronic7</a></td>
        <td>1</td>
        <td>9882.867</td>
        <td>1215.000</td>
    </tr>
    <tr>
        <td>2532</td>
        <td><a href=players.php?pid=20872&edition=5>Kten_</a></td>
        <td>1</td>
        <td>9882.880</td>
        <td>1216.000</td>
    </tr>
    <tr>
        <td>2533</td>
        <td><a href=players.php?pid=27154&edition=5>BoomByron</a></td>
        <td>1</td>
        <td>9882.960</td>
        <td>1222.000</td>
    </tr>
    <tr>
        <td>2534</td>
        <td><a href=players.php?pid=69892&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;NSDKrEW</span></a></td>
        <td>1</td>
        <td>9882.960</td>
        <td>1222.000</td>
    </tr>
    <tr>
        <td>2535</td>
        <td><a href=players.php?pid=43512&edition=5>Zackadidou</a></td>
        <td>1</td>
        <td>9882.973</td>
        <td>1223.000</td>
    </tr>
    <tr>
        <td>2536</td>
        <td><a href=players.php?pid=65867&edition=5>oyoySA</a></td>
        <td>1</td>
        <td>9883.013</td>
        <td>1226.000</td>
    </tr>
    <tr>
        <td>2537</td>
        <td><a href=players.php?pid=67407&edition=5>Phxots_19</a></td>
        <td>1</td>
        <td>9883.093</td>
        <td>1232.000</td>
    </tr>
    <tr>
        <td>2538</td>
        <td><a href=players.php?pid=36299&edition=5>Nisub_</a></td>
        <td>1</td>
        <td>9883.120</td>
        <td>1234.000</td>
    </tr>
    <tr>
        <td>2539</td>
        <td><a href=players.php?pid=34137&edition=5>rmayhem</a></td>
        <td>1</td>
        <td>9883.133</td>
        <td>1235.000</td>
    </tr>
    <tr>
        <td>2540</td>
        <td><a href=players.php?pid=53734&edition=5>WedDec</a></td>
        <td>1</td>
        <td>9883.187</td>
        <td>1239.000</td>
    </tr>
    <tr>
        <td>2541</td>
        <td><a href=players.php?pid=66904&edition=5>KlotzkopfTM</a></td>
        <td>1</td>
        <td>9883.200</td>
        <td>1240.000</td>
    </tr>
    <tr>
        <td>2542</td>
        <td><a href=players.php?pid=72433&edition=5>Itzyourboizac3</a></td>
        <td>1</td>
        <td>9883.227</td>
        <td>1242.000</td>
    </tr>
    <tr>
        <td>2543</td>
        <td><a href=players.php?pid=67870&edition=5>ion_2x</a></td>
        <td>1</td>
        <td>9883.240</td>
        <td>1243.000</td>
    </tr>
    <tr>
        <td>2544</td>
        <td><a href=players.php?pid=44582&edition=5>Cleum</a></td>
        <td>1</td>
        <td>9883.307</td>
        <td>1248.000</td>
    </tr>
    <tr>
        <td>2545</td>
        <td><a href=players.php?pid=2862&edition=5>aussiegolferttv</a></td>
        <td>1</td>
        <td>9883.347</td>
        <td>1251.000</td>
    </tr>
    <tr>
        <td>2546</td>
        <td><a href=players.php?pid=54363&edition=5>crossygod77</a></td>
        <td>1</td>
        <td>9883.387</td>
        <td>1254.000</td>
    </tr>
    <tr>
        <td>2547</td>
        <td><a href=players.php?pid=70219&edition=5>Domyy_VAMOS</a></td>
        <td>1</td>
        <td>9883.413</td>
        <td>1256.000</td>
    </tr>
    <tr>
        <td>2548</td>
        <td><a href=players.php?pid=52148&edition=5>IndieSaisive&nbsp;heh</a></td>
        <td>1</td>
        <td>9883.427</td>
        <td>1257.000</td>
    </tr>
    <tr>
        <td>2549</td>
        <td><a href=players.php?pid=68854&edition=5>JARO256</a></td>
        <td>1</td>
        <td>9883.467</td>
        <td>1260.000</td>
    </tr>
    <tr>
        <td>2550</td>
        <td><a href=players.php?pid=10633&edition=5>Inho41</a></td>
        <td>1</td>
        <td>9883.493</td>
        <td>1262.000</td>
    </tr>
    <tr>
        <td>2551</td>
        <td><a href=players.php?pid=33005&edition=5>valgoid</a></td>
        <td>1</td>
        <td>9883.533</td>
        <td>1265.000</td>
    </tr>
    <tr>
        <td>2552</td>
        <td><a href=players.php?pid=67195&edition=5>&lt;<span style='color:#00bb00;font-style:italic;'>A</span><span
                    style='color:#dd9900;font-style:italic;'>y</span><span
                    style='color:#00bb00;font-style:italic;'>y</span><span
                    style='color:#000000;font-style:italic;'>-</span><span
                    style='color:#dd9900;font-style:italic;'>J</span><span
                    style='color:#00bb00;font-style:italic;'>a</span><span
                    style='color:#dd9900;font-style:italic;'>x</span>&gt;</a></td>
        <td>1</td>
        <td>9883.560</td>
        <td>1267.000</td>
    </tr>
    <tr>
        <td>2553</td>
        <td><a href=players.php?pid=64300&edition=5>tjoices</a></td>
        <td>1</td>
        <td>9883.573</td>
        <td>1268.000</td>
    </tr>
    <tr>
        <td>2554</td>
        <td><a href=players.php?pid=6597&edition=5>Vizirrr</a></td>
        <td>1</td>
        <td>9883.587</td>
        <td>1269.000</td>
    </tr>
    <tr>
        <td>2555</td>
        <td><a href=players.php?pid=41773&edition=5>Vexefus</a></td>
        <td>1</td>
        <td>9883.600</td>
        <td>1270.000</td>
    </tr>
    <tr>
        <td>2556</td>
        <td><a href=players.php?pid=71084&edition=5>iHawkie</a></td>
        <td>1</td>
        <td>9883.600</td>
        <td>1270.000</td>
    </tr>
    <tr>
        <td>2557</td>
        <td><a href=players.php?pid=66086&edition=5>AJLogan1</a></td>
        <td>1</td>
        <td>9883.733</td>
        <td>1280.000</td>
    </tr>
    <tr>
        <td>2558</td>
        <td><a href=players.php?pid=67191&edition=5>H_M_Murdoc</a></td>
        <td>1</td>
        <td>9883.760</td>
        <td>1282.000</td>
    </tr>
    <tr>
        <td>2559</td>
        <td><a href=players.php?pid=49775&edition=5>kielon</a></td>
        <td>1</td>
        <td>9883.813</td>
        <td>1286.000</td>
    </tr>
    <tr>
        <td>2560</td>
        <td><a href=players.php?pid=50587&edition=5>Blue_Arsen</a></td>
        <td>1</td>
        <td>9883.827</td>
        <td>1287.000</td>
    </tr>
    <tr>
        <td>2561</td>
        <td><a href=players.php?pid=67379&edition=5>fre_D0m</a></td>
        <td>1</td>
        <td>9883.853</td>
        <td>1289.000</td>
    </tr>
    <tr>
        <td>2562</td>
        <td><a href=players.php?pid=45719&edition=5>fox_boyyy</a></td>
        <td>1</td>
        <td>9883.867</td>
        <td>1290.000</td>
    </tr>
    <tr>
        <td>2563</td>
        <td><a href=players.php?pid=66889&edition=5><span style='color:#6699ee;'>t</span><span
                    style='color:#7788ee;'>h</span><span style='color:#7788dd;'>3</span><span
                    style='color:#8877dd;'>b</span><span style='color:#9966cc;'>a</span><span
                    style='color:#aa66cc;'>l</span><span style='color:#aa55bb;'>d</span><span
                    style='color:#bb44bb;'>n</span><span style='color:#cc33aa;'>er</span><span
                    style='color:#dd2299;'>d</span></a></td>
        <td>1</td>
        <td>9883.893</td>
        <td>1292.000</td>
    </tr>
    <tr>
        <td>2564</td>
        <td><a href=players.php?pid=32506&edition=5>Am4ced</a></td>
        <td>1</td>
        <td>9883.947</td>
        <td>1296.000</td>
    </tr>
    <tr>
        <td>2565</td>
        <td><a href=players.php?pid=46152&edition=5>Coldrift</a></td>
        <td>1</td>
        <td>9883.973</td>
        <td>1298.000</td>
    </tr>
    <tr>
        <td>2566</td>
        <td><a href=players.php?pid=7779&edition=5>Schwiftysquanch</a></td>
        <td>1</td>
        <td>9883.973</td>
        <td>1298.000</td>
    </tr>
    <tr>
        <td>2567</td>
        <td><a href=players.php?pid=66044&edition=5>Manty.</a></td>
        <td>1</td>
        <td>9884.000</td>
        <td>1300.000</td>
    </tr>
    <tr>
        <td>2568</td>
        <td><a href=players.php?pid=60104&edition=5>Ninjaquacamole</a></td>
        <td>1</td>
        <td>9884.013</td>
        <td>1301.000</td>
    </tr>
    <tr>
        <td>2569</td>
        <td><a href=players.php?pid=14839&edition=5>WattZonFire</a></td>
        <td>1</td>
        <td>9884.053</td>
        <td>1304.000</td>
    </tr>
    <tr>
        <td>2570</td>
        <td><a href=players.php?pid=19353&edition=5>Dillerkok</a></td>
        <td>1</td>
        <td>9884.067</td>
        <td>1305.000</td>
    </tr>
    <tr>
        <td>2571</td>
        <td><a href=players.php?pid=9631&edition=5><span style='color:#222222;'>c</span><span
                    style='color:#333333;'>o</span><span style='color:#444444;'>ut</span><span
                    style='color:#555555;'>e</span><span style='color:#666666;'>!</span></a></td>
        <td>1</td>
        <td>9884.093</td>
        <td>1307.000</td>
    </tr>
    <tr>
        <td>2572</td>
        <td><a href=players.php?pid=57338&edition=5>Kresiaaa</a></td>
        <td>1</td>
        <td>9884.133</td>
        <td>1310.000</td>
    </tr>
    <tr>
        <td>2573</td>
        <td><a href=players.php?pid=50034&edition=5>P529</a></td>
        <td>1</td>
        <td>9884.133</td>
        <td>1310.000</td>
    </tr>
    <tr>
        <td>2574</td>
        <td><a href=players.php?pid=46208&edition=5>RedXST</a></td>
        <td>1</td>
        <td>9884.160</td>
        <td>1312.000</td>
    </tr>
    <tr>
        <td>2575</td>
        <td><a href=players.php?pid=69172&edition=5>CyIex</a></td>
        <td>1</td>
        <td>9884.187</td>
        <td>1314.000</td>
    </tr>
    <tr>
        <td>2576</td>
        <td><a href=players.php?pid=55805&edition=5>LeftIsFaster</a></td>
        <td>1</td>
        <td>9884.253</td>
        <td>1319.000</td>
    </tr>
    <tr>
        <td>2577</td>
        <td><a href=players.php?pid=29048&edition=5><span style='color:#33ff00;'>Ţ</span><span
                    style='color:#33ff44;'>ป</span><span style='color:#33ff88;'>_</span><span
                    style='color:#33ffbb;'>Л</span><span style='color:#33ffff;'>म</span><span
                    style='color:#33ffff;'>ﾅ</span><span style='color:#66ffbb;'>Ţ</span><span
                    style='color:#99ff88;'>Ħ</span><span style='color:#ccff44;'>&epsilon;</span><span
                    style='color:#ffff00;'>ѿ</span></a></td>
        <td>1</td>
        <td>9884.307</td>
        <td>1323.000</td>
    </tr>
    <tr>
        <td>2578</td>
        <td><a href=players.php?pid=15770&edition=5>Twyzzyx</a></td>
        <td>1</td>
        <td>9884.347</td>
        <td>1326.000</td>
    </tr>
    <tr>
        <td>2579</td>
        <td><a href=players.php?pid=70645&edition=5>Driftsy11</a></td>
        <td>1</td>
        <td>9884.360</td>
        <td>1327.000</td>
    </tr>
    <tr>
        <td>2580</td>
        <td><a href=players.php?pid=67456&edition=5>J94601</a></td>
        <td>1</td>
        <td>9884.387</td>
        <td>1329.000</td>
    </tr>
    <tr>
        <td>2581</td>
        <td><a href=players.php?pid=32260&edition=5>BlastnorTM</a></td>
        <td>1</td>
        <td>9884.400</td>
        <td>1330.000</td>
    </tr>
    <tr>
        <td>2582</td>
        <td><a href=players.php?pid=68071&edition=5><span style='color:#ffccdd;font-weight:bold;'>Tumble</span><span
                    style='color:#aaddee;font-weight:bold;'>weed._</span></a></td>
        <td>1</td>
        <td>9884.413</td>
        <td>1331.000</td>
    </tr>
    <tr>
        <td>2583</td>
        <td><a href=players.php?pid=71223&edition=5>Def0nceMan</a></td>
        <td>1</td>
        <td>9884.440</td>
        <td>1333.000</td>
    </tr>
    <tr>
        <td>2584</td>
        <td><a href=players.php?pid=23834&edition=5>decplayz</a></td>
        <td>1</td>
        <td>9884.453</td>
        <td>1334.000</td>
    </tr>
    <tr>
        <td>2585</td>
        <td><a href=players.php?pid=66900&edition=5>TheStone02</a></td>
        <td>1</td>
        <td>9884.547</td>
        <td>1341.000</td>
    </tr>
    <tr>
        <td>2586</td>
        <td><a href=players.php?pid=59495&edition=5>NiKoS-355</a></td>
        <td>1</td>
        <td>9884.613</td>
        <td>1346.000</td>
    </tr>
    <tr>
        <td>2587</td>
        <td><a href=players.php?pid=62865&edition=5>BR00V</a></td>
        <td>1</td>
        <td>9884.627</td>
        <td>1347.000</td>
    </tr>
    <tr>
        <td>2588</td>
        <td><a href=players.php?pid=29620&edition=5>PyromaneQc</a></td>
        <td>1</td>
        <td>9884.640</td>
        <td>1348.000</td>
    </tr>
    <tr>
        <td>2589</td>
        <td><a href=players.php?pid=62787&edition=5>ArSkAgOeSnOoB</a></td>
        <td>1</td>
        <td>9884.667</td>
        <td>1350.000</td>
    </tr>
    <tr>
        <td>2590</td>
        <td><a href=players.php?pid=71145&edition=5>Xil4ncer</a></td>
        <td>1</td>
        <td>9884.733</td>
        <td>1355.000</td>
    </tr>
    <tr>
        <td>2591</td>
        <td><a href=players.php?pid=45583&edition=5>TrueFrostyyy</a></td>
        <td>1</td>
        <td>9884.747</td>
        <td>1356.000</td>
    </tr>
    <tr>
        <td>2592</td>
        <td><a href=players.php?pid=16205&edition=5><span style='color:#ff0033;'>f</span><span
                    style='color:#ff0055;'>r</span><span style='color:#ff0088;'>o</span><span
                    style='color:#ff00aa;'>d</span><span style='color:#ff00cc;'>o</span><span
                    style='color:#ff00cc;'>t</span><span style='color:#ff0099;'>i</span><span
                    style='color:#ff0066;'>a</span><span style='color:#ff0033;'>n</span></a></td>
        <td>1</td>
        <td>9884.773</td>
        <td>1358.000</td>
    </tr>
    <tr>
        <td>2593</td>
        <td><a href=players.php?pid=66085&edition=5>Emmersling</a></td>
        <td>1</td>
        <td>9884.800</td>
        <td>1360.000</td>
    </tr>
    <tr>
        <td>2594</td>
        <td><a href=players.php?pid=72041&edition=5>KR_Raxxou</a></td>
        <td>1</td>
        <td>9884.827</td>
        <td>1362.000</td>
    </tr>
    <tr>
        <td>2595</td>
        <td><a href=players.php?pid=18076&edition=5>Zorago-</a></td>
        <td>1</td>
        <td>9884.853</td>
        <td>1364.000</td>
    </tr>
    <tr>
        <td>2596</td>
        <td><a href=players.php?pid=63188&edition=5>Tjobbie</a></td>
        <td>1</td>
        <td>9884.920</td>
        <td>1369.000</td>
    </tr>
    <tr>
        <td>2597</td>
        <td><a href=players.php?pid=67649&edition=5>Gr1sen</a></td>
        <td>1</td>
        <td>9884.973</td>
        <td>1373.000</td>
    </tr>
    <tr>
        <td>2598</td>
        <td><a href=players.php?pid=59745&edition=5><span style='color:#0000ff;font-weight:bold;'>ALEX</span></a></td>
        <td>1</td>
        <td>9885.040</td>
        <td>1378.000</td>
    </tr>
    <tr>
        <td>2599</td>
        <td><a href=players.php?pid=65121&edition=5>rhyswhy</a></td>
        <td>1</td>
        <td>9885.067</td>
        <td>1380.000</td>
    </tr>
    <tr>
        <td>2600</td>
        <td><a href=players.php?pid=44841&edition=5><span style='color:#00ff00;'>[</span><span
                    style='color:#00ff33;'>ﾅ</span><span style='color:#00ff66;'>Z</span><span
                    style='color:#00ff66;'>Ѧ</span><span style='color:#00ff33;'>]&nbsp;</span><span
                    style='color:#00ff33;'>S</span><span style='color:#008822;'>p</span><span
                    style='color:#000000;'>o</span><span style='color:#000000;'>n</span><span
                    style='color:#008822;'>k</span><span style='color:#00ff33;'>y</span></a></td>
        <td>1</td>
        <td>9885.080</td>
        <td>1381.000</td>
    </tr>
    <tr>
        <td>2601</td>
        <td><a href=players.php?pid=66532&edition=5>sandalz_</a></td>
        <td>1</td>
        <td>9885.107</td>
        <td>1383.000</td>
    </tr>
    <tr>
        <td>2602</td>
        <td><a href=players.php?pid=46445&edition=5><span style='color:#ff0000;'>ѵ</span><span
                    style='color:#cc0000;'>i</span><span style='color:#990000;'>r</span><span
                    style='color:#660000;'>t</span><span style='color:#330000;'>u</span><span
                    style='color:#000000;'>o</span></a></td>
        <td>1</td>
        <td>9885.120</td>
        <td>1384.000</td>
    </tr>
    <tr>
        <td>2603</td>
        <td><a href=players.php?pid=71157&edition=5>Fleeeeeeeex</a></td>
        <td>1</td>
        <td>9885.120</td>
        <td>1384.000</td>
    </tr>
    <tr>
        <td>2604</td>
        <td><a href=players.php?pid=68404&edition=5>FercOMoAz</a></td>
        <td>1</td>
        <td>9885.133</td>
        <td>1385.000</td>
    </tr>
    <tr>
        <td>2605</td>
        <td><a href=players.php?pid=69159&edition=5>superstriker745</a></td>
        <td>1</td>
        <td>9885.187</td>
        <td>1389.000</td>
    </tr>
    <tr>
        <td>2606</td>
        <td><a href=players.php?pid=66126&edition=5>Chrisyboylol</a></td>
        <td>1</td>
        <td>9885.213</td>
        <td>1391.000</td>
    </tr>
    <tr>
        <td>2607</td>
        <td><a href=players.php?pid=69009&edition=5>GoldenAeroTM</a></td>
        <td>1</td>
        <td>9885.267</td>
        <td>1395.000</td>
    </tr>
    <tr>
        <td>2608</td>
        <td><a href=players.php?pid=49916&edition=5>s:owo:nity&nbsp;fan</a></td>
        <td>1</td>
        <td>9885.280</td>
        <td>1396.000</td>
    </tr>
    <tr>
        <td>2609</td>
        <td><a href=players.php?pid=67063&edition=5>Muki..</a></td>
        <td>1</td>
        <td>9885.293</td>
        <td>1397.000</td>
    </tr>
    <tr>
        <td>2610</td>
        <td><a href=players.php?pid=45551&edition=5>ProtatoV2</a></td>
        <td>1</td>
        <td>9885.320</td>
        <td>1399.000</td>
    </tr>
    <tr>
        <td>2611</td>
        <td><a href=players.php?pid=69303&edition=5>DrDogTrucK</a></td>
        <td>1</td>
        <td>9885.387</td>
        <td>1404.000</td>
    </tr>
    <tr>
        <td>2612</td>
        <td><a href=players.php?pid=67307&edition=5>pade</a></td>
        <td>1</td>
        <td>9885.507</td>
        <td>1413.000</td>
    </tr>
    <tr>
        <td>2613</td>
        <td><a href=players.php?pid=66589&edition=5>osammo7</a></td>
        <td>1</td>
        <td>9885.520</td>
        <td>1414.000</td>
    </tr>
    <tr>
        <td>2614</td>
        <td><a href=players.php?pid=67333&edition=5>KeithingItReal</a></td>
        <td>1</td>
        <td>9885.560</td>
        <td>1417.000</td>
    </tr>
    <tr>
        <td>2615</td>
        <td><a href=players.php?pid=61667&edition=5>Nebelben</a></td>
        <td>1</td>
        <td>9885.613</td>
        <td>1421.000</td>
    </tr>
    <tr>
        <td>2616</td>
        <td><a href=players.php?pid=56784&edition=5>EtyanTheGod</a></td>
        <td>1</td>
        <td>9885.613</td>
        <td>1421.000</td>
    </tr>
    <tr>
        <td>2617</td>
        <td><a href=players.php?pid=70549&edition=5>Paiffekapp</a></td>
        <td>1</td>
        <td>9885.640</td>
        <td>1423.000</td>
    </tr>
    <tr>
        <td>2618</td>
        <td><a href=players.php?pid=49987&edition=5>Cytexx44</a></td>
        <td>1</td>
        <td>9885.653</td>
        <td>1424.000</td>
    </tr>
    <tr>
        <td>2619</td>
        <td><a href=players.php?pid=66769&edition=5>GergoAutoPC</a></td>
        <td>1</td>
        <td>9885.693</td>
        <td>1427.000</td>
    </tr>
    <tr>
        <td>2620</td>
        <td><a href=players.php?pid=47886&edition=5>djk6516</a></td>
        <td>1</td>
        <td>9885.707</td>
        <td>1428.000</td>
    </tr>
    <tr>
        <td>2621</td>
        <td><a href=players.php?pid=68532&edition=5>Ho2Positive</a></td>
        <td>1</td>
        <td>9885.720</td>
        <td>1429.000</td>
    </tr>
    <tr>
        <td>2622</td>
        <td><a href=players.php?pid=35534&edition=5>fogirox</a></td>
        <td>1</td>
        <td>9885.733</td>
        <td>1430.000</td>
    </tr>
    <tr>
        <td>2623</td>
        <td><a href=players.php?pid=19743&edition=5>grand--</a></td>
        <td>1</td>
        <td>9885.853</td>
        <td>1439.000</td>
    </tr>
    <tr>
        <td>2624</td>
        <td><a href=players.php?pid=33863&edition=5>IcyzLim</a></td>
        <td>1</td>
        <td>9885.867</td>
        <td>1440.000</td>
    </tr>
    <tr>
        <td>2625</td>
        <td><a href=players.php?pid=67528&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;P21_TM</span></a></td>
        <td>1</td>
        <td>9885.907</td>
        <td>1443.000</td>
    </tr>
    <tr>
        <td>2626</td>
        <td><a href=players.php?pid=16213&edition=5>LukaszW</a></td>
        <td>1</td>
        <td>9885.960</td>
        <td>1447.000</td>
    </tr>
    <tr>
        <td>2627</td>
        <td><a href=players.php?pid=66514&edition=5>xXxProKill</a></td>
        <td>1</td>
        <td>9885.973</td>
        <td>1448.000</td>
    </tr>
    <tr>
        <td>2628</td>
        <td><a href=players.php?pid=67898&edition=5>Tommie._</a></td>
        <td>1</td>
        <td>9886.027</td>
        <td>1452.000</td>
    </tr>
    <tr>
        <td>2629</td>
        <td><a href=players.php?pid=15830&edition=5>Gonszcz.</a></td>
        <td>1</td>
        <td>9886.040</td>
        <td>1453.000</td>
    </tr>
    <tr>
        <td>2630</td>
        <td><a href=players.php?pid=10454&edition=5>Leellismith</a></td>
        <td>1</td>
        <td>9886.053</td>
        <td>1454.000</td>
    </tr>
    <tr>
        <td>2631</td>
        <td><a href=players.php?pid=70188&edition=5>WatchBenGo</a></td>
        <td>1</td>
        <td>9886.080</td>
        <td>1456.000</td>
    </tr>
    <tr>
        <td>2632</td>
        <td><a href=players.php?pid=40159&edition=5>ki_marv453</a></td>
        <td>1</td>
        <td>9886.147</td>
        <td>1461.000</td>
    </tr>
    <tr>
        <td>2633</td>
        <td><a href=players.php?pid=67046&edition=5>BBN.Pockit</a></td>
        <td>1</td>
        <td>9886.187</td>
        <td>1464.000</td>
    </tr>
    <tr>
        <td>2634</td>
        <td><a href=players.php?pid=18002&edition=5>PFratt</a></td>
        <td>1</td>
        <td>9886.213</td>
        <td>1466.000</td>
    </tr>
    <tr>
        <td>2635</td>
        <td><a href=players.php?pid=71931&edition=5>ALBu.</a></td>
        <td>1</td>
        <td>9886.280</td>
        <td>1471.000</td>
    </tr>
    <tr>
        <td>2636</td>
        <td><a href=players.php?pid=69778&edition=5>omkarguda</a></td>
        <td>1</td>
        <td>9886.293</td>
        <td>1472.000</td>
    </tr>
    <tr>
        <td>2637</td>
        <td><a href=players.php?pid=67433&edition=5>skitix1</a></td>
        <td>1</td>
        <td>9886.320</td>
        <td>1474.000</td>
    </tr>
    <tr>
        <td>2638</td>
        <td><a href=players.php?pid=13622&edition=5>isi_25</a></td>
        <td>1</td>
        <td>9886.373</td>
        <td>1478.000</td>
    </tr>
    <tr>
        <td>2639</td>
        <td><a href=players.php?pid=70563&edition=5>reyn0lds_023</a></td>
        <td>1</td>
        <td>9886.413</td>
        <td>1481.000</td>
    </tr>
    <tr>
        <td>2640</td>
        <td><a href=players.php?pid=37602&edition=5>bexted.</a></td>
        <td>1</td>
        <td>9886.440</td>
        <td>1483.000</td>
    </tr>
    <tr>
        <td>2641</td>
        <td><a href=players.php?pid=63229&edition=5>ponczek.com.pl</a></td>
        <td>1</td>
        <td>9886.480</td>
        <td>1486.000</td>
    </tr>
    <tr>
        <td>2642</td>
        <td><a href=players.php?pid=69886&edition=5>ElwenEltaco</a></td>
        <td>1</td>
        <td>9886.627</td>
        <td>1497.000</td>
    </tr>
    <tr>
        <td>2643</td>
        <td><a href=players.php?pid=70221&edition=5>CongeeZee</a></td>
        <td>1</td>
        <td>9886.720</td>
        <td>1504.000</td>
    </tr>
    <tr>
        <td>2644</td>
        <td><a href=players.php?pid=58299&edition=5>ghokiemc</a></td>
        <td>1</td>
        <td>9886.733</td>
        <td>1505.000</td>
    </tr>
    <tr>
        <td>2645</td>
        <td><a href=players.php?pid=22441&edition=5>Stuba1404</a></td>
        <td>1</td>
        <td>9886.827</td>
        <td>1512.000</td>
    </tr>
    <tr>
        <td>2646</td>
        <td><a href=players.php?pid=21288&edition=5>SilverHeat27</a></td>
        <td>1</td>
        <td>9886.920</td>
        <td>1519.000</td>
    </tr>
    <tr>
        <td>2647</td>
        <td><a href=players.php?pid=71239&edition=5>andybizzzle</a></td>
        <td>1</td>
        <td>9886.960</td>
        <td>1522.000</td>
    </tr>
    <tr>
        <td>2648</td>
        <td><a href=players.php?pid=52794&edition=5>Fvbbri</a></td>
        <td>1</td>
        <td>9886.987</td>
        <td>1524.000</td>
    </tr>
    <tr>
        <td>2649</td>
        <td><a href=players.php?pid=21380&edition=5>teizxamos</a></td>
        <td>1</td>
        <td>9887.013</td>
        <td>1526.000</td>
    </tr>
    <tr>
        <td>2650</td>
        <td><a href=players.php?pid=72018&edition=5>ThorFRocks</a></td>
        <td>1</td>
        <td>9887.067</td>
        <td>1530.000</td>
    </tr>
    <tr>
        <td>2651</td>
        <td><a href=players.php?pid=67422&edition=5>TheDeltora</a></td>
        <td>1</td>
        <td>9887.107</td>
        <td>1533.000</td>
    </tr>
    <tr>
        <td>2652</td>
        <td><a href=players.php?pid=30744&edition=5>Krinkstone</a></td>
        <td>1</td>
        <td>9887.133</td>
        <td>1535.000</td>
    </tr>
    <tr>
        <td>2653</td>
        <td><a href=players.php?pid=68405&edition=5>fitty1182</a></td>
        <td>1</td>
        <td>9887.173</td>
        <td>1538.000</td>
    </tr>
    <tr>
        <td>2654</td>
        <td><a href=players.php?pid=42665&edition=5><span style='color:#ff0000;'>r</span>0<span
                    style='color:#ffaa00;'>d</span><span style='color:#ffff00;'>r</span></a></td>
        <td>1</td>
        <td>9887.200</td>
        <td>1540.000</td>
    </tr>
    <tr>
        <td>2655</td>
        <td><a href=players.php?pid=52133&edition=5><span style='color:#00dd00;font-weight:bold;'>GLORP</span></a></td>
        <td>1</td>
        <td>9887.213</td>
        <td>1541.000</td>
    </tr>
    <tr>
        <td>2656</td>
        <td><a href=players.php?pid=72522&edition=5>Vadi0._</a></td>
        <td>1</td>
        <td>9887.253</td>
        <td>1544.000</td>
    </tr>
    <tr>
        <td>2657</td>
        <td><a href=players.php?pid=6534&edition=5>greentea._</a></td>
        <td>1</td>
        <td>9887.333</td>
        <td>1550.000</td>
    </tr>
    <tr>
        <td>2658</td>
        <td><a href=players.php?pid=58570&edition=5>Grog_TM</a></td>
        <td>1</td>
        <td>9887.440</td>
        <td>1558.000</td>
    </tr>
    <tr>
        <td>2659</td>
        <td><a href=players.php?pid=55510&edition=5>Nebbie.TM</a></td>
        <td>1</td>
        <td>9887.453</td>
        <td>1559.000</td>
    </tr>
    <tr>
        <td>2660</td>
        <td><a href=players.php?pid=12335&edition=5><span style='color:#000000;'>&upsilon;</span><span
                    style='color:#666600;'>ה</span><span style='color:#cccc00;'>Я</span><span
                    style='color:#cccc00;'>e</span><span style='color:#666600;'>&alpha;</span><span
                    style='color:#000000;'>Ŀ</span></a></td>
        <td>1</td>
        <td>9887.493</td>
        <td>1562.000</td>
    </tr>
    <tr>
        <td>2661</td>
        <td><a href=players.php?pid=67495&edition=5>fiddler112</a></td>
        <td>1</td>
        <td>9887.520</td>
        <td>1564.000</td>
    </tr>
    <tr>
        <td>2662</td>
        <td><a href=players.php?pid=51413&edition=5>Vilamar234</a></td>
        <td>1</td>
        <td>9887.547</td>
        <td>1566.000</td>
    </tr>
    <tr>
        <td>2663</td>
        <td><a href=players.php?pid=58330&edition=5>lucian____</a></td>
        <td>1</td>
        <td>9887.600</td>
        <td>1570.000</td>
    </tr>
    <tr>
        <td>2664</td>
        <td><a href=players.php?pid=16206&edition=5>Racco_N</a></td>
        <td>1</td>
        <td>9887.613</td>
        <td>1571.000</td>
    </tr>
    <tr>
        <td>2665</td>
        <td><a href=players.php?pid=1537&edition=5>Enibeti</a></td>
        <td>1</td>
        <td>9887.627</td>
        <td>1572.000</td>
    </tr>
    <tr>
        <td>2666</td>
        <td><a href=players.php?pid=69407&edition=5>ivanraez</a></td>
        <td>1</td>
        <td>9887.747</td>
        <td>1581.000</td>
    </tr>
    <tr>
        <td>2667</td>
        <td><a href=players.php?pid=41040&edition=5>lupusVI</a></td>
        <td>1</td>
        <td>9887.800</td>
        <td>1585.000</td>
    </tr>
    <tr>
        <td>2668</td>
        <td><a href=players.php?pid=48002&edition=5>lebronultrafan</a></td>
        <td>1</td>
        <td>9887.840</td>
        <td>1588.000</td>
    </tr>
    <tr>
        <td>2669</td>
        <td><a href=players.php?pid=69389&edition=5>Marvins1309</a></td>
        <td>1</td>
        <td>9887.853</td>
        <td>1589.000</td>
    </tr>
    <tr>
        <td>2670</td>
        <td><a href=players.php?pid=72509&edition=5>Tm_Kyu</a></td>
        <td>1</td>
        <td>9887.880</td>
        <td>1591.000</td>
    </tr>
    <tr>
        <td>2671</td>
        <td><a href=players.php?pid=28701&edition=5>nick1509</a></td>
        <td>1</td>
        <td>9887.907</td>
        <td>1593.000</td>
    </tr>
    <tr>
        <td>2672</td>
        <td><a href=players.php?pid=68344&edition=5>DeathsComing4U</a></td>
        <td>1</td>
        <td>9887.920</td>
        <td>1594.000</td>
    </tr>
    <tr>
        <td>2673</td>
        <td><a href=players.php?pid=70264&edition=5>loganwt1</a></td>
        <td>1</td>
        <td>9887.933</td>
        <td>1595.000</td>
    </tr>
    <tr>
        <td>2674</td>
        <td><a href=players.php?pid=9076&edition=5>LruggTM</a></td>
        <td>1</td>
        <td>9887.947</td>
        <td>1596.000</td>
    </tr>
    <tr>
        <td>2675</td>
        <td><a href=players.php?pid=71511&edition=5>rainb0wkeyb0ard</a></td>
        <td>1</td>
        <td>9887.973</td>
        <td>1598.000</td>
    </tr>
    <tr>
        <td>2676</td>
        <td><a href=players.php?pid=37016&edition=5><span style='color:#55ccdd;'>W</span><span
                    style='color:#77ccdd;'>a</span><span style='color:#88ccee;'>v</span><span
                    style='color:#ddeeff;'>e</span><span style='color:#ffddff;'>s</span><span
                    style='color:#ee99dd;'>_</span><span style='color:#dd66dd;'>T</span><span
                    style='color:#dd44bb;'>M</span></a></td>
        <td>1</td>
        <td>9888.000</td>
        <td>1600.000</td>
    </tr>
    <tr>
        <td>2677</td>
        <td><a href=players.php?pid=18591&edition=5>Broddan.</a></td>
        <td>1</td>
        <td>9888.040</td>
        <td>1603.000</td>
    </tr>
    <tr>
        <td>2678</td>
        <td><a href=players.php?pid=61675&edition=5>Disaster444</a></td>
        <td>1</td>
        <td>9888.107</td>
        <td>1608.000</td>
    </tr>
    <tr>
        <td>2679</td>
        <td><a href=players.php?pid=67156&edition=5>RandomJohnnyR</a></td>
        <td>1</td>
        <td>9888.187</td>
        <td>1614.000</td>
    </tr>
    <tr>
        <td>2680</td>
        <td><a href=players.php?pid=51180&edition=5>Pure_chaos666</a></td>
        <td>1</td>
        <td>9888.320</td>
        <td>1624.000</td>
    </tr>
    <tr>
        <td>2681</td>
        <td><a href=players.php?pid=66632&edition=5>ottah_</a></td>
        <td>1</td>
        <td>9888.427</td>
        <td>1632.000</td>
    </tr>
    <tr>
        <td>2682</td>
        <td><a href=players.php?pid=66896&edition=5>Ghysaa</a></td>
        <td>1</td>
        <td>9888.547</td>
        <td>1641.000</td>
    </tr>
    <tr>
        <td>2683</td>
        <td><a href=players.php?pid=59955&edition=5>CastleBucket</a></td>
        <td>1</td>
        <td>9888.600</td>
        <td>1645.000</td>
    </tr>
    <tr>
        <td>2684</td>
        <td><a href=players.php?pid=67660&edition=5>TheSnugglar</a></td>
        <td>1</td>
        <td>9888.640</td>
        <td>1648.000</td>
    </tr>
    <tr>
        <td>2685</td>
        <td><a href=players.php?pid=66560&edition=5><span style='color:#990099;'>D-9D</span></a></td>
        <td>1</td>
        <td>9888.653</td>
        <td>1649.000</td>
    </tr>
    <tr>
        <td>2686</td>
        <td><a href=players.php?pid=8406&edition=5>kanzo_</a></td>
        <td>1</td>
        <td>9888.680</td>
        <td>1651.000</td>
    </tr>
    <tr>
        <td>2687</td>
        <td><a href=players.php?pid=66476&edition=5>BluFalafel999</a></td>
        <td>1</td>
        <td>9888.747</td>
        <td>1656.000</td>
    </tr>
    <tr>
        <td>2688</td>
        <td><a href=players.php?pid=30151&edition=5><span
                    style='color:#0000ff;'>&nbsp;Zewo&nbsp;is&nbsp;bad&nbsp;at&nbsp;kacky</span></a></td>
        <td>1</td>
        <td>9888.813</td>
        <td>1661.000</td>
    </tr>
    <tr>
        <td>2689</td>
        <td><a href=players.php?pid=71387&edition=5>TheSantasRock</a></td>
        <td>1</td>
        <td>9888.827</td>
        <td>1662.000</td>
    </tr>
    <tr>
        <td>2690</td>
        <td><a href=players.php?pid=2216&edition=5>DensetsuGG</a></td>
        <td>1</td>
        <td>9888.840</td>
        <td>1663.000</td>
    </tr>
    <tr>
        <td>2691</td>
        <td><a href=players.php?pid=49624&edition=5>kpelitoxd</a></td>
        <td>1</td>
        <td>9888.867</td>
        <td>1665.000</td>
    </tr>
    <tr>
        <td>2692</td>
        <td><a href=players.php?pid=69724&edition=5>Jus198</a></td>
        <td>1</td>
        <td>9888.920</td>
        <td>1669.000</td>
    </tr>
    <tr>
        <td>2693</td>
        <td><a href=players.php?pid=70134&edition=5>DABMOTM</a></td>
        <td>1</td>
        <td>9888.960</td>
        <td>1672.000</td>
    </tr>
    <tr>
        <td>2694</td>
        <td><a href=players.php?pid=66331&edition=5><span style='color:#bbee88;'>D</span><span
                    style='color:#aaee99;'>a</span><span style='color:#aaee99;'>n</span><span
                    style='color:#99eeaa;'>n</span><span style='color:#99ddaa;'>i</span><span
                    style='color:#88ddaa;'>s</span><span style='color:#88ddbb;'>s</span><span
                    style='color:#77ddbb;'>a</span><span style='color:#66ddcc;'>r</span><span
                    style='color:#66ddcc;'>i</span><span style='color:#55ddcc;'>o</span></a></td>
        <td>1</td>
        <td>9889.093</td>
        <td>1682.000</td>
    </tr>
    <tr>
        <td>2695</td>
        <td><a href=players.php?pid=43039&edition=5>ManaToon</a></td>
        <td>1</td>
        <td>9889.147</td>
        <td>1686.000</td>
    </tr>
    <tr>
        <td>2696</td>
        <td><a href=players.php?pid=30510&edition=5>J0K3R_Damaged</a></td>
        <td>1</td>
        <td>9889.333</td>
        <td>1700.000</td>
    </tr>
    <tr>
        <td>2697</td>
        <td><a href=players.php?pid=64878&edition=5>Karton155</a></td>
        <td>1</td>
        <td>9889.360</td>
        <td>1702.000</td>
    </tr>
    <tr>
        <td>2698</td>
        <td><a href=players.php?pid=11861&edition=5>H3Harry</a></td>
        <td>1</td>
        <td>9889.400</td>
        <td>1705.000</td>
    </tr>
    <tr>
        <td>2699</td>
        <td><a href=players.php?pid=70911&edition=5>Boeing_fighter</a></td>
        <td>1</td>
        <td>9889.413</td>
        <td>1706.000</td>
    </tr>
    <tr>
        <td>2700</td>
        <td><a href=players.php?pid=69854&edition=5>Dhordrim</a></td>
        <td>1</td>
        <td>9889.427</td>
        <td>1707.000</td>
    </tr>
    <tr>
        <td>2701</td>
        <td><a href=players.php?pid=50187&edition=5>RaidingDolphin</a></td>
        <td>1</td>
        <td>9889.440</td>
        <td>1708.000</td>
    </tr>
    <tr>
        <td>2702</td>
        <td><a href=players.php?pid=32668&edition=5>Marsh_h</a></td>
        <td>1</td>
        <td>9889.507</td>
        <td>1713.000</td>
    </tr>
    <tr>
        <td>2703</td>
        <td><a href=players.php?pid=34794&edition=5>Tofu64</a></td>
        <td>1</td>
        <td>9889.587</td>
        <td>1719.000</td>
    </tr>
    <tr>
        <td>2704</td>
        <td><a href=players.php?pid=65122&edition=5>Clutchx-</a></td>
        <td>1</td>
        <td>9889.720</td>
        <td>1729.000</td>
    </tr>
    <tr>
        <td>2705</td>
        <td><a href=players.php?pid=967&edition=5>Nekolodeon</a></td>
        <td>1</td>
        <td>9889.733</td>
        <td>1730.000</td>
    </tr>
    <tr>
        <td>2706</td>
        <td><a href=players.php?pid=1624&edition=5>julestar.</a></td>
        <td>1</td>
        <td>9889.813</td>
        <td>1736.000</td>
    </tr>
    <tr>
        <td>2707</td>
        <td><a href=players.php?pid=66300&edition=5>ImATree2024</a></td>
        <td>1</td>
        <td>9889.840</td>
        <td>1738.000</td>
    </tr>
    <tr>
        <td>2708</td>
        <td><a href=players.php?pid=70724&edition=5>Now59</a></td>
        <td>1</td>
        <td>9889.867</td>
        <td>1740.000</td>
    </tr>
    <tr>
        <td>2709</td>
        <td><a href=players.php?pid=28198&edition=5>Haegiz42</a></td>
        <td>1</td>
        <td>9889.880</td>
        <td>1741.000</td>
    </tr>
    <tr>
        <td>2710</td>
        <td><a href=players.php?pid=68227&edition=5>lmining</a></td>
        <td>1</td>
        <td>9889.920</td>
        <td>1744.000</td>
    </tr>
    <tr>
        <td>2711</td>
        <td><a href=players.php?pid=70280&edition=5>Rk_Retro</a></td>
        <td>1</td>
        <td>9889.960</td>
        <td>1747.000</td>
    </tr>
    <tr>
        <td>2712</td>
        <td><a href=players.php?pid=26386&edition=5>Riza_HD</a></td>
        <td>1</td>
        <td>9889.973</td>
        <td>1748.000</td>
    </tr>
    <tr>
        <td>2713</td>
        <td><a href=players.php?pid=68737&edition=5>hayster777</a></td>
        <td>1</td>
        <td>9890.013</td>
        <td>1751.000</td>
    </tr>
    <tr>
        <td>2714</td>
        <td><a href=players.php?pid=12071&edition=5><span style='color:#ff7700;'>C</span><span
                    style='color:#ffffff;'>O</span><span style='color:#ff7700;'>T&nbsp;</span><span
                    style='color:#ffffff;'>&nbsp;|&nbsp;</span><span style='color:#ffffff;'>&nbsp;</span><span
                    style='color:#cc00ff;'>N</span><span style='color:#aa00ff;'>a</span><span
                    style='color:#7700ff;'>i</span><span style='color:#5500ff;'>S</span><span
                    style='color:#2200ff;'>S</span><span style='color:#0000ff;'>a</span><span
                    style='color:#0000ff;'>x</span><span style='color:#2211ff;'>D</span><span
                    style='color:#4411ff;'>r</span><span style='color:#5522ff;'>e</span><span
                    style='color:#7722ff;'>a</span><span style='color:#9933ff;'>m</span></a></td>
        <td>1</td>
        <td>9890.093</td>
        <td>1757.000</td>
    </tr>
    <tr>
        <td>2715</td>
        <td><a href=players.php?pid=70137&edition=5>PoIybius</a></td>
        <td>1</td>
        <td>9890.160</td>
        <td>1762.000</td>
    </tr>
    <tr>
        <td>2716</td>
        <td><a href=players.php?pid=68180&edition=5>lolomye</a></td>
        <td>1</td>
        <td>9890.173</td>
        <td>1763.000</td>
    </tr>
    <tr>
        <td>2717</td>
        <td><a href=players.php?pid=69788&edition=5>Fullertunaboat</a></td>
        <td>1</td>
        <td>9890.213</td>
        <td>1766.000</td>
    </tr>
    <tr>
        <td>2718</td>
        <td><a href=players.php?pid=17175&edition=5>EmilianaH</a></td>
        <td>1</td>
        <td>9890.227</td>
        <td>1767.000</td>
    </tr>
    <tr>
        <td>2719</td>
        <td><a href=players.php?pid=63429&edition=5>FightnFact</a></td>
        <td>1</td>
        <td>9890.240</td>
        <td>1768.000</td>
    </tr>
    <tr>
        <td>2720</td>
        <td><a href=players.php?pid=62822&edition=5>wyrchi_</a></td>
        <td>1</td>
        <td>9890.293</td>
        <td>1772.000</td>
    </tr>
    <tr>
        <td>2721</td>
        <td><a href=players.php?pid=49826&edition=5>EddyTM_</a></td>
        <td>1</td>
        <td>9890.387</td>
        <td>1779.000</td>
    </tr>
    <tr>
        <td>2722</td>
        <td><a href=players.php?pid=25094&edition=5>D3miseTM</a></td>
        <td>1</td>
        <td>9890.413</td>
        <td>1781.000</td>
    </tr>
    <tr>
        <td>2723</td>
        <td><a href=players.php?pid=46416&edition=5>Huskyfanatic</a></td>
        <td>1</td>
        <td>9890.480</td>
        <td>1786.000</td>
    </tr>
    <tr>
        <td>2724</td>
        <td><a href=players.php?pid=69312&edition=5>DMCroww</a></td>
        <td>1</td>
        <td>9890.533</td>
        <td>1790.000</td>
    </tr>
    <tr>
        <td>2725</td>
        <td><a href=players.php?pid=70180&edition=5>Sha9win</a></td>
        <td>1</td>
        <td>9890.640</td>
        <td>1798.000</td>
    </tr>
    <tr>
        <td>2726</td>
        <td><a href=players.php?pid=2811&edition=5>faer.TM</a></td>
        <td>1</td>
        <td>9890.667</td>
        <td>1800.000</td>
    </tr>
    <tr>
        <td>2727</td>
        <td><a href=players.php?pid=65842&edition=5>Blade.57</a></td>
        <td>1</td>
        <td>9890.680</td>
        <td>1801.000</td>
    </tr>
    <tr>
        <td>2728</td>
        <td><a href=players.php?pid=48952&edition=5>ApocLovesNekos</a></td>
        <td>1</td>
        <td>9890.693</td>
        <td>1802.000</td>
    </tr>
    <tr>
        <td>2729</td>
        <td><a href=players.php?pid=69134&edition=5>elestofao</a></td>
        <td>1</td>
        <td>9890.707</td>
        <td>1803.000</td>
    </tr>
    <tr>
        <td>2730</td>
        <td><a href=players.php?pid=26281&edition=5>neon_05.</a></td>
        <td>1</td>
        <td>9890.720</td>
        <td>1804.000</td>
    </tr>
    <tr>
        <td>2731</td>
        <td><a href=players.php?pid=21957&edition=5>CHILBERT</a></td>
        <td>1</td>
        <td>9890.747</td>
        <td>1806.000</td>
    </tr>
    <tr>
        <td>2732</td>
        <td><a href=players.php?pid=655&edition=5>Quatre_Z</a></td>
        <td>1</td>
        <td>9890.787</td>
        <td>1809.000</td>
    </tr>
    <tr>
        <td>2733</td>
        <td><a href=players.php?pid=68514&edition=5>PenileMutilator</a></td>
        <td>1</td>
        <td>9890.853</td>
        <td>1814.000</td>
    </tr>
    <tr>
        <td>2734</td>
        <td><a href=players.php?pid=72405&edition=5>JathOsh</a></td>
        <td>1</td>
        <td>9890.880</td>
        <td>1816.000</td>
    </tr>
    <tr>
        <td>2735</td>
        <td><a href=players.php?pid=68051&edition=5>Rainbaguette</a></td>
        <td>1</td>
        <td>9890.960</td>
        <td>1822.000</td>
    </tr>
    <tr>
        <td>2736</td>
        <td><a href=players.php?pid=71754&edition=5>Chewwey</a></td>
        <td>1</td>
        <td>9890.987</td>
        <td>1824.000</td>
    </tr>
    <tr>
        <td>2737</td>
        <td><a href=players.php?pid=31718&edition=5><span style='color:#1155dd;'>I</span><span
                    style='color:#1166dd;'>g</span><span style='color:#2277dd;'>n</span><span
                    style='color:#3377ee;'>o</span><span style='color:#4488ee;'>r</span><span
                    style='color:#5599ee;'>&nbsp;</span><span style='color:#55aaff;'>2</span><span
                    style='color:#66aaff;'>1</span></a></td>
        <td>1</td>
        <td>9891.067</td>
        <td>1830.000</td>
    </tr>
    <tr>
        <td>2738</td>
        <td><a href=players.php?pid=35754&edition=5><span style='color:#ff0000;'>D</span><span
                    style='color:#bb5566;'>e</span><span style='color:#6699cc;'>g</span><span
                    style='color:#6699cc;'>n</span><span style='color:#ff0000;'>o</span></a></td>
        <td>1</td>
        <td>9891.107</td>
        <td>1833.000</td>
    </tr>
    <tr>
        <td>2739</td>
        <td><a href=players.php?pid=24185&edition=5>Tricycle_57e</a></td>
        <td>1</td>
        <td>9891.120</td>
        <td>1834.000</td>
    </tr>
    <tr>
        <td>2740</td>
        <td><a href=players.php?pid=68812&edition=5>SensonW</a></td>
        <td>1</td>
        <td>9891.187</td>
        <td>1839.000</td>
    </tr>
    <tr>
        <td>2741</td>
        <td><a href=players.php?pid=68704&edition=5>TechTechPotato</a></td>
        <td>1</td>
        <td>9891.240</td>
        <td>1843.000</td>
    </tr>
    <tr>
        <td>2742</td>
        <td><a href=players.php?pid=67060&edition=5>arlyy0815</a></td>
        <td>1</td>
        <td>9891.507</td>
        <td>1863.000</td>
    </tr>
    <tr>
        <td>2743</td>
        <td><a href=players.php?pid=25498&edition=5>Six9Pixels.4PF</a></td>
        <td>1</td>
        <td>9891.520</td>
        <td>1864.000</td>
    </tr>
    <tr>
        <td>2744</td>
        <td><a href=players.php?pid=10729&edition=5>N30NWH4L3</a></td>
        <td>1</td>
        <td>9891.560</td>
        <td>1867.000</td>
    </tr>
    <tr>
        <td>2745</td>
        <td><a href=players.php?pid=67626&edition=5>soledady</a></td>
        <td>1</td>
        <td>9891.627</td>
        <td>1872.000</td>
    </tr>
    <tr>
        <td>2746</td>
        <td><a href=players.php?pid=68215&edition=5>MEREGA1</a></td>
        <td>1</td>
        <td>9891.693</td>
        <td>1877.000</td>
    </tr>
    <tr>
        <td>2747</td>
        <td><a href=players.php?pid=39176&edition=5><span style='color:#ff3300;'>S</span><span
                    style='color:#dd4400;'>e</span><span style='color:#aa4400;'>g</span><span
                    style='color:#885500;'>o</span><span style='color:#555500;font-weight:bold;'>и</span><span
                    style='color:#336600;font-weight:bold;'>h</span><span
                    style='color:#006600;font-weight:bold;'>o</span></a></td>
        <td>1</td>
        <td>9891.707</td>
        <td>1878.000</td>
    </tr>
    <tr>
        <td>2748</td>
        <td><a href=players.php?pid=70639&edition=5>tseaton3</a></td>
        <td>1</td>
        <td>9891.773</td>
        <td>1883.000</td>
    </tr>
    <tr>
        <td>2749</td>
        <td><a href=players.php?pid=69388&edition=5>randomvidzz</a></td>
        <td>1</td>
        <td>9891.813</td>
        <td>1886.000</td>
    </tr>
    <tr>
        <td>2750</td>
        <td><a href=players.php?pid=6621&edition=5><span style='color:#55ccff;'>E</span><span
                    style='color:#88ddff;'>P</span><span style='color:#aaeeff;'>a</span><span
                    style='color:#ddeeff;'>n</span><span style='color:#ffffff;'>d</span><span
                    style='color:#ffffff;'>a</span><span style='color:#ffeeee;'>4</span>0<span
                    style='color:#ffbbcc;'>4</span></a></td>
        <td>1</td>
        <td>9891.840</td>
        <td>1888.000</td>
    </tr>
    <tr>
        <td>2751</td>
        <td><a href=players.php?pid=69079&edition=5>ProvokedBanana</a></td>
        <td>1</td>
        <td>9891.907</td>
        <td>1893.000</td>
    </tr>
    <tr>
        <td>2752</td>
        <td><a href=players.php?pid=71949&edition=5>MiIkshake</a></td>
        <td>1</td>
        <td>9891.947</td>
        <td>1896.000</td>
    </tr>
    <tr>
        <td>2753</td>
        <td><a href=players.php?pid=376&edition=5>Yezop</a></td>
        <td>1</td>
        <td>9892.000</td>
        <td>1900.000</td>
    </tr>
    <tr>
        <td>2754</td>
        <td><a href=players.php?pid=66285&edition=5>Doscha514</a></td>
        <td>1</td>
        <td>9892.067</td>
        <td>1905.000</td>
    </tr>
    <tr>
        <td>2755</td>
        <td><a href=players.php?pid=67535&edition=5>Modozi</a></td>
        <td>1</td>
        <td>9892.080</td>
        <td>1906.000</td>
    </tr>
    <tr>
        <td>2756</td>
        <td><a href=players.php?pid=26187&edition=5>The5torm</a></td>
        <td>1</td>
        <td>9892.093</td>
        <td>1907.000</td>
    </tr>
    <tr>
        <td>2757</td>
        <td><a href=players.php?pid=70083&edition=5>Panprezi0</a></td>
        <td>1</td>
        <td>9892.107</td>
        <td>1908.000</td>
    </tr>
    <tr>
        <td>2758</td>
        <td><a href=players.php?pid=54900&edition=5>HedgeTM</a></td>
        <td>1</td>
        <td>9892.120</td>
        <td>1909.000</td>
    </tr>
    <tr>
        <td>2759</td>
        <td><a href=players.php?pid=68448&edition=5>Kroppsdel</a></td>
        <td>1</td>
        <td>9892.147</td>
        <td>1911.000</td>
    </tr>
    <tr>
        <td>2760</td>
        <td><a href=players.php?pid=59143&edition=5>SwatFux</a></td>
        <td>1</td>
        <td>9892.160</td>
        <td>1912.000</td>
    </tr>
    <tr>
        <td>2761</td>
        <td><a href=players.php?pid=67631&edition=5>peter_tm</a></td>
        <td>1</td>
        <td>9892.173</td>
        <td>1913.000</td>
    </tr>
    <tr>
        <td>2762</td>
        <td><a href=players.php?pid=30369&edition=5><span style='color:#cccc00;'>v</span><span
                    style='color:#88cc55;'>Ǻ</span><span style='color:#44ccaa;'>Ҳ</span><span
                    style='color:#00ccff;'>囟</span></a></td>
        <td>1</td>
        <td>9892.213</td>
        <td>1916.000</td>
    </tr>
    <tr>
        <td>2763</td>
        <td><a href=players.php?pid=68651&edition=5>zygis16</a></td>
        <td>1</td>
        <td>9892.253</td>
        <td>1919.000</td>
    </tr>
    <tr>
        <td>2764</td>
        <td><a href=players.php?pid=66498&edition=5>Bugungo.</a></td>
        <td>1</td>
        <td>9892.293</td>
        <td>1922.000</td>
    </tr>
    <tr>
        <td>2765</td>
        <td><a href=players.php?pid=7777&edition=5>micheleeee</a></td>
        <td>1</td>
        <td>9892.333</td>
        <td>1925.000</td>
    </tr>
    <tr>
        <td>2766</td>
        <td><a href=players.php?pid=52169&edition=5>Vinyl_TM</a></td>
        <td>1</td>
        <td>9892.347</td>
        <td>1926.000</td>
    </tr>
    <tr>
        <td>2767</td>
        <td><a href=players.php?pid=67546&edition=5>CHRLZ_</a></td>
        <td>1</td>
        <td>9892.400</td>
        <td>1930.000</td>
    </tr>
    <tr>
        <td>2768</td>
        <td><a href=players.php?pid=35666&edition=5>hofla74</a></td>
        <td>1</td>
        <td>9892.467</td>
        <td>1935.000</td>
    </tr>
    <tr>
        <td>2769</td>
        <td><a href=players.php?pid=7431&edition=5>Donkelburg</a></td>
        <td>1</td>
        <td>9892.480</td>
        <td>1936.000</td>
    </tr>
    <tr>
        <td>2770</td>
        <td><a href=players.php?pid=64488&edition=5>Crowieeee</a></td>
        <td>1</td>
        <td>9892.493</td>
        <td>1937.000</td>
    </tr>
    <tr>
        <td>2771</td>
        <td><a href=players.php?pid=39648&edition=5>JustFelix08</a></td>
        <td>1</td>
        <td>9892.507</td>
        <td>1938.000</td>
    </tr>
    <tr>
        <td>2772</td>
        <td><a href=players.php?pid=52641&edition=5>Matmo9130</a></td>
        <td>1</td>
        <td>9892.533</td>
        <td>1940.000</td>
    </tr>
    <tr>
        <td>2773</td>
        <td><a href=players.php?pid=67406&edition=5>ShadowSword416</a></td>
        <td>1</td>
        <td>9892.560</td>
        <td>1942.000</td>
    </tr>
    <tr>
        <td>2774</td>
        <td><a href=players.php?pid=64439&edition=5>Gad-.</a></td>
        <td>1</td>
        <td>9892.573</td>
        <td>1943.000</td>
    </tr>
    <tr>
        <td>2775</td>
        <td><a href=players.php?pid=70627&edition=5>Wingzy_</a></td>
        <td>1</td>
        <td>9892.667</td>
        <td>1950.000</td>
    </tr>
    <tr>
        <td>2776</td>
        <td><a href=players.php?pid=28935&edition=5>snuhVeli</a></td>
        <td>1</td>
        <td>9892.680</td>
        <td>1951.000</td>
    </tr>
    <tr>
        <td>2777</td>
        <td><a href=players.php?pid=4151&edition=5>AK-Infinite2</a></td>
        <td>1</td>
        <td>9892.693</td>
        <td>1952.000</td>
    </tr>
    <tr>
        <td>2778</td>
        <td><a href=players.php?pid=70406&edition=5>LiljonL01</a></td>
        <td>1</td>
        <td>9892.707</td>
        <td>1953.000</td>
    </tr>
    <tr>
        <td>2779</td>
        <td><a href=players.php?pid=52728&edition=5>NickSD91</a></td>
        <td>1</td>
        <td>9892.733</td>
        <td>1955.000</td>
    </tr>
    <tr>
        <td>2780</td>
        <td><a href=players.php?pid=29143&edition=5>LittleBearTM</a></td>
        <td>1</td>
        <td>9892.760</td>
        <td>1957.000</td>
    </tr>
    <tr>
        <td>2781</td>
        <td><a href=players.php?pid=68923&edition=5>SlowMW</a></td>
        <td>1</td>
        <td>9892.840</td>
        <td>1963.000</td>
    </tr>
    <tr>
        <td>2782</td>
        <td><a href=players.php?pid=18382&edition=5>Ch4r0n999</a></td>
        <td>1</td>
        <td>9892.960</td>
        <td>1972.000</td>
    </tr>
    <tr>
        <td>2783</td>
        <td><a href=players.php?pid=69739&edition=5>peterretep04</a></td>
        <td>1</td>
        <td>9892.987</td>
        <td>1974.000</td>
    </tr>
    <tr>
        <td>2784</td>
        <td><a href=players.php?pid=71268&edition=5>MattSric</a></td>
        <td>1</td>
        <td>9893.040</td>
        <td>1978.000</td>
    </tr>
    <tr>
        <td>2785</td>
        <td><a href=players.php?pid=18991&edition=5>Leftie520</a></td>
        <td>1</td>
        <td>9893.053</td>
        <td>1979.000</td>
    </tr>
    <tr>
        <td>2786</td>
        <td><a href=players.php?pid=41898&edition=5>OneOnTheVine</a></td>
        <td>1</td>
        <td>9893.107</td>
        <td>1983.000</td>
    </tr>
    <tr>
        <td>2787</td>
        <td><a href=players.php?pid=66533&edition=5>rhz..</a></td>
        <td>1</td>
        <td>9893.120</td>
        <td>1984.000</td>
    </tr>
    <tr>
        <td>2788</td>
        <td><a href=players.php?pid=70466&edition=5>SenaSmrt</a></td>
        <td>1</td>
        <td>9893.147</td>
        <td>1986.000</td>
    </tr>
    <tr>
        <td>2789</td>
        <td><a href=players.php?pid=65092&edition=5>Yannick__38</a></td>
        <td>1</td>
        <td>9893.160</td>
        <td>1987.000</td>
    </tr>
    <tr>
        <td>2790</td>
        <td><a href=players.php?pid=17437&edition=5><span style='color:#0000ff;'>R</span><span
                    style='color:#ffffff;'>ench</span><span style='color:#0000ff;'>I</span></a></td>
        <td>1</td>
        <td>9893.187</td>
        <td>1989.000</td>
    </tr>
    <tr>
        <td>2791</td>
        <td><a href=players.php?pid=33310&edition=5>tntaap</a></td>
        <td>1</td>
        <td>9893.200</td>
        <td>1990.000</td>
    </tr>
    <tr>
        <td>2792</td>
        <td><a href=players.php?pid=12902&edition=5>QlowB</a></td>
        <td>1</td>
        <td>9893.227</td>
        <td>1992.000</td>
    </tr>
    <tr>
        <td>2793</td>
        <td><a href=players.php?pid=70072&edition=5>Arsenic.TM</a></td>
        <td>1</td>
        <td>9893.253</td>
        <td>1994.000</td>
    </tr>
    <tr>
        <td>2794</td>
        <td><a href=players.php?pid=66183&edition=5>TheBLoved</a></td>
        <td>1</td>
        <td>9893.280</td>
        <td>1996.000</td>
    </tr>
    <tr>
        <td>2795</td>
        <td><a href=players.php?pid=66559&edition=5>BicuriousGoose</a></td>
        <td>1</td>
        <td>9893.293</td>
        <td>1997.000</td>
    </tr>
    <tr>
        <td>2796</td>
        <td><a href=players.php?pid=49199&edition=5>Hoschighg</a></td>
        <td>1</td>
        <td>9893.387</td>
        <td>2004.000</td>
    </tr>
    <tr>
        <td>2797</td>
        <td><a href=players.php?pid=54471&edition=5>crazytuxbanana</a></td>
        <td>1</td>
        <td>9893.427</td>
        <td>2007.000</td>
    </tr>
    <tr>
        <td>2798</td>
        <td><a href=players.php?pid=47855&edition=5>Osens_</a></td>
        <td>1</td>
        <td>9893.440</td>
        <td>2008.000</td>
    </tr>
    <tr>
        <td>2799</td>
        <td><a href=players.php?pid=51121&edition=5>Carter_B_13</a></td>
        <td>1</td>
        <td>9893.453</td>
        <td>2009.000</td>
    </tr>
    <tr>
        <td>2800</td>
        <td><a href=players.php?pid=70360&edition=5>EK_Infix</a></td>
        <td>1</td>
        <td>9893.480</td>
        <td>2011.000</td>
    </tr>
    <tr>
        <td>2801</td>
        <td><a href=players.php?pid=69825&edition=5>adamdarek</a></td>
        <td>1</td>
        <td>9893.493</td>
        <td>2012.000</td>
    </tr>
    <tr>
        <td>2802</td>
        <td><a href=players.php?pid=70343&edition=5>sjansonus</a></td>
        <td>1</td>
        <td>9893.653</td>
        <td>2024.000</td>
    </tr>
    <tr>
        <td>2803</td>
        <td><a href=players.php?pid=67226&edition=5>TGR_ORE</a></td>
        <td>1</td>
        <td>9893.680</td>
        <td>2026.000</td>
    </tr>
    <tr>
        <td>2804</td>
        <td><a href=players.php?pid=58868&edition=5>ArcticAden_TM</a></td>
        <td>1</td>
        <td>9893.707</td>
        <td>2028.000</td>
    </tr>
    <tr>
        <td>2805</td>
        <td><a href=players.php?pid=66646&edition=5>Galdiorin</a></td>
        <td>1</td>
        <td>9893.733</td>
        <td>2030.000</td>
    </tr>
    <tr>
        <td>2806</td>
        <td><a href=players.php?pid=62046&edition=5>Keto6668</a></td>
        <td>1</td>
        <td>9893.813</td>
        <td>2036.000</td>
    </tr>
    <tr>
        <td>2807</td>
        <td><a href=players.php?pid=9886&edition=5>Liquiditious</a></td>
        <td>1</td>
        <td>9893.880</td>
        <td>2041.000</td>
    </tr>
    <tr>
        <td>2808</td>
        <td><a href=players.php?pid=30457&edition=5>Aerosia314</a></td>
        <td>1</td>
        <td>9893.893</td>
        <td>2042.000</td>
    </tr>
    <tr>
        <td>2809</td>
        <td><a href=players.php?pid=31735&edition=5>Pirat1ca</a></td>
        <td>1</td>
        <td>9893.907</td>
        <td>2043.000</td>
    </tr>
    <tr>
        <td>2810</td>
        <td><a href=players.php?pid=31034&edition=5>Darian24.</a></td>
        <td>1</td>
        <td>9893.933</td>
        <td>2045.000</td>
    </tr>
    <tr>
        <td>2811</td>
        <td><a href=players.php?pid=53199&edition=5>Matuu2</a></td>
        <td>1</td>
        <td>9893.960</td>
        <td>2047.000</td>
    </tr>
    <tr>
        <td>2812</td>
        <td><a href=players.php?pid=17535&edition=5>sver006</a></td>
        <td>1</td>
        <td>9894.013</td>
        <td>2051.000</td>
    </tr>
    <tr>
        <td>2813</td>
        <td><a href=players.php?pid=55090&edition=5>leddhedd</a></td>
        <td>1</td>
        <td>9894.187</td>
        <td>2064.000</td>
    </tr>
    <tr>
        <td>2814</td>
        <td><a href=players.php?pid=32431&edition=5>XV27</a></td>
        <td>1</td>
        <td>9894.213</td>
        <td>2066.000</td>
    </tr>
    <tr>
        <td>2815</td>
        <td><a href=players.php?pid=19873&edition=5>Robugas</a></td>
        <td>1</td>
        <td>9894.307</td>
        <td>2073.000</td>
    </tr>
    <tr>
        <td>2816</td>
        <td><a href=players.php?pid=33229&edition=5><span style='color:#0033ff;'>C</span><span
                    style='color:#002288;'>i</span><span style='color:#000000;'>s</span><span
                    style='color:#000000;'>c</span><span style='color:#22aa33;'>o</span></a></td>
        <td>1</td>
        <td>9894.360</td>
        <td>2077.000</td>
    </tr>
    <tr>
        <td>2817</td>
        <td><a href=players.php?pid=22406&edition=5>UnoSvenningsson</a></td>
        <td>1</td>
        <td>9894.467</td>
        <td>2085.000</td>
    </tr>
    <tr>
        <td>2818</td>
        <td><a href=players.php?pid=4836&edition=5>Naywon</a></td>
        <td>1</td>
        <td>9894.493</td>
        <td>2087.000</td>
    </tr>
    <tr>
        <td>2819</td>
        <td><a href=players.php?pid=70236&edition=5>itsRosey</a></td>
        <td>1</td>
        <td>9894.520</td>
        <td>2089.000</td>
    </tr>
    <tr>
        <td>2820</td>
        <td><a href=players.php?pid=4182&edition=5>snuffieh</a></td>
        <td>1</td>
        <td>9894.533</td>
        <td>2090.000</td>
    </tr>
    <tr>
        <td>2821</td>
        <td><a href=players.php?pid=51811&edition=5>LimettenJunkie</a></td>
        <td>1</td>
        <td>9894.547</td>
        <td>2091.000</td>
    </tr>
    <tr>
        <td>2822</td>
        <td><a href=players.php?pid=69191&edition=5>JSteaf</a></td>
        <td>1</td>
        <td>9894.560</td>
        <td>2092.000</td>
    </tr>
    <tr>
        <td>2823</td>
        <td><a href=players.php?pid=12266&edition=5><span style='color:#ffaa88;font-weight:bold;'>JAVE</span></a></td>
        <td>1</td>
        <td>9894.613</td>
        <td>2096.000</td>
    </tr>
    <tr>
        <td>2824</td>
        <td><a href=players.php?pid=60562&edition=5>BruhHour</a></td>
        <td>1</td>
        <td>9894.680</td>
        <td>2101.000</td>
    </tr>
    <tr>
        <td>2825</td>
        <td><a href=players.php?pid=70633&edition=5>LauWheeler</a></td>
        <td>1</td>
        <td>9894.733</td>
        <td>2105.000</td>
    </tr>
    <tr>
        <td>2826</td>
        <td><a href=players.php?pid=72497&edition=5>Symb&nbsp;<span style='color:#ff9900;'>:</span><span
                    style='color:#ee7700;'>s</span><span style='color:#ee5500;'>m</span><span
                    style='color:#dd2200;'>i</span><span style='color:#cc0000;'>r</span><span
                    style='color:#cc0000;'>k</span><span style='color:#bb0044;'>c</span><span
                    style='color:#990088;'>a</span><span style='color:#8800bb;'>t</span><span
                    style='color:#6600ff;'>:</span></a></td>
        <td>1</td>
        <td>9894.747</td>
        <td>2106.000</td>
    </tr>
    <tr>
        <td>2827</td>
        <td><a href=players.php?pid=63587&edition=5>Reztile2021</a></td>
        <td>1</td>
        <td>9894.827</td>
        <td>2112.000</td>
    </tr>
    <tr>
        <td>2828</td>
        <td><a href=players.php?pid=4036&edition=5>RIAG95</a></td>
        <td>1</td>
        <td>9894.840</td>
        <td>2113.000</td>
    </tr>
"""
