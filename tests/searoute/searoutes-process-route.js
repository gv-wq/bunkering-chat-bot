import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm";
let config = {
  supabase: {
    url: Deno.env.get("SUPABASE_URL"),
    serviceKey: Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")
  },
  searoutes: {
    token: Deno.env.get("SEAROUTES_TOKEN"),
    reqPerMinute: 60
  },
  bubble: {
    token: Deno.env.get("BUBBLE_TOKEN"),
    dataApiSleepMs: 500,
    batchSize: 100
  }
};
console.log(`Init supabase client`);
export const supabase = createClient(config.supabase.url, config.supabase.serviceKey);


serve(async (req)=>{
  const reqBody = await req.text();
  const reqJson = JSON.parse(reqBody);
  const initialResponse = new Response(JSON.stringify({
    message: "Processing started"
  }), {
    headers: {
      "Content-Type": "application/json"
    }
  });



  const wpfs = reqJson.detailed_plan.features[0].properties.waypoints.features;

  processPorts(reqJson.route_id, wpfs, reqJson.deviation, reqJson.version, reqJson.fetch_all == 1).then(()=>{
    console.log("Route processing completed!");
  }).catch((err)=>{
    console.error("Error processing route:", err);
  });
  return initialResponse;
});









async function sleep(ms) {
  return new Promise((resolve)=>setTimeout(resolve, ms));
}












async function processPorts(routeId, waypointFeatures, deviation, version = "test", fetchAll = false) {
  let ports = [];
  const baseUrl = version === "live" ? Deno.env.get("BUBBLE_BASE_URL_LIVE") : Deno.env.get("BUBBLE_BASE_URL_TEST");
  console.log(`Process ${waypointFeatures.length} waypoint(s), deviation ${deviation}m for route ${routeId}`);
  try {
    for (const wpf of waypointFeatures){
      const lat = wpf.geometry.coordinates[0];
      const lon = wpf.geometry.coordinates[1];
      await sleep(60000 / config.searoutes.reqPerMinute);
      const params = `?locationTypes=port&limit=50&radius=${deviation}`;
      const response = await fetch(`https://api.searoutes.com/geocoding/v2/closest/${lat},${lon}${params}`, {
        headers: {
          "x-api-key": config.searoutes.token
        }
      });
      if (response.ok) {
        const data = await response.json();
        const newPorts = data.features.map((f)=>{
          return {
            ...f.properties,
            eta: wpf.properties.timestamp,
            lat: f.geometry.coordinates[0],
            lon: f.geometry.coordinates[1]
          };
        });
        ports = [
          ...ports,
          ...newPorts
        ];
      } else {
        console.error(`Failed to fetch ports for waypoint ${lat}, ${lon}`);
      }
      console.log(`Found ${ports.length} port(s) so far, waypoint ${lat},${lon}`);
    }
    const uniquePorts = Array.from(new Map(ports.map((port)=>[
        port.locode,
        port
      ])).values()).sort((a, b)=>{
      if (a.dateOfArrival && b.dateOfArrival) {
        return new Date(a.dateOfArrival).getTime() - new Date(b.dateOfArrival).getTime();
      }
      return 0;
    });



    try {
      const { data, error } = await supabase.from("port").upsert(uniquePorts.map((p)=>{
        console.debug(p);
        return {
          name: p.name,
          locode: p.locode?.toLowerCase(),
          country_code: p.countryCode?.toLowerCase(),
          country_name: p.countryName,
          location_type: p.locationType?.toLowerCase() || "port",
          is_seca: p.isSeca || false,
          size: p.size,
          lon: p.lon,
          lat: p.lat
        };
      }), {
        onConflict: [
          "locode"
        ]
      }).select();
      if (error) {
        console.warn("Error saving ports:", error.message);
        console.warn(error);
      }
    } catch (err) {
      console.error("Unexpected error:", err);
    }
    let existingPorts = [];
    const locodes = ports.map((p)=>p.locode);
    let lcBatches = chunkArray(locodes, config.bubble.batchSize);
    console.log(`Check ${uniquePorts.length} port(s) for new entries in ${lcBatches.length} batches`);
    for (const batch of lcBatches){
      const fetchedPorts = await getMany(baseUrl, config.bubble.token, "port", [
        {
          "key": "locode_text",
          "constraint_type": "in",
          "value": batch
        }
      ]);
      existingPorts = [
        ...existingPorts,
        ...fetchedPorts
      ];
    }
    let missingPorts = uniquePorts.filter((p)=>!existingPorts.some((e)=>e.locode === p.locode));
    const portsToCreate = missingPorts.map((port)=>({
        "name": port.name,
        "locode": port.locode,
        "sr_country_name": port.countryName,
        "sr_lat": port.lat,
        "sr_lon": port.lon
      }));
    console.log(`Cache ${portsToCreate.length} new port(s)`);
    if (portsToCreate.length > 0) {
      const createdPorts = await createMany(baseUrl, config.bubble.token, "port", portsToCreate);
    }
    existingPorts = [];
    lcBatches = chunkArray(locodes, config.bubble.batchSize);
    console.log(`Re-check ${uniquePorts.length} port(s) for new entries in ${lcBatches.length} batches`);
    for (const batch of lcBatches){
      const fetchedPorts = await getMany(baseUrl, config.bubble.token, "port", [
        {
          "key": "locode_text",
          "constraint_type": "in",
          "value": batch
        }
      ]);
      existingPorts = [
        ...existingPorts,
        ...fetchedPorts
      ];
    }
    missingPorts = uniquePorts.filter((p)=>!existingPorts.some((e)=>e.locode === p.locode));
    if (missingPorts.length > 0) {
      console.error(`Ports still missing after update!`);
      return;
    }
    const routePortsToCreate = uniquePorts.map((port)=>{
      const matchingPorts = existingPorts.filter((p)=>{
        return p.locode.toLowerCase() == port.locode.toLowerCase();
      }).filter((p)=>{
        return fetchAll || whitelistedLocodes.some((lc)=>{
          return lc.toLowerCase() == p.locode.toLowerCase();
        });
      });
      if (matchingPorts.length > 0) {
        return {
          "route": routeId,
          "port": matchingPorts[0]._id,
          "eta": port.eta,
          "distance_m": port.distance
        };
      }
      return null;
    }).filter((p)=>p != null);
    console.log(`Create ${routePortsToCreate.length} new route port(s)`);
    if (routePortsToCreate.length > 0) {
      const createdRoutePorts = await createMany(baseUrl, config.bubble.token, "route_port", routePortsToCreate);
    }
    const routeData = await getMany(baseUrl, config.bubble.token, "route", [
      {
        "key": "_id",
        "constraint_type": "equals",
        "value": routeId
      }
    ]);
    if (routeData[0]?.status !== "Failed") {
      await updateOne(baseUrl, config.bubble.token, "route", routeId, {
        "status": "Complete"
      });
    } else {
      console.error(`Route ${routeId} has status Failed`);
    }
  } catch (error) {
    console.error("Error processing ports:", error);
    await updateOne(baseUrl, config.bubble.token, "route", routeId, {
      "status": "Failed"
    });
  }
}











function chunkArray(array, size) {
  const result = [];
  for(let i = 0; i < array.length; i += size)result.push(array.slice(i, i + size));
  return result;
}













async function fetchBubble(url, method, token, body) {
  const headers = {
    "Authorization": `Bearer ${token}`,
    "Content-Type": method == "POST" ? "text/plain" : "application/json"
  };
  const response = await fetch(url, {
    method: method,
    headers: headers,
    body: body
  });
  if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
  const responseBody = await response.text();
  try {
    return JSON.parse(responseBody);
  } catch (err) {
    const jsonObjects = responseBody.split("\n").filter((line)=>line.trim()).map((line)=>JSON.parse(line));
    return jsonObjects;
  }
}













async function getMany(baseUrl, token, type, filters) {
  const endpoint = `${baseUrl}${type}`;
  let objList = [];
  let offset = 0;
  let remaining = 0;
  const constraints = filters ? `&constraints=${encodeURIComponent(JSON.stringify(filters))}` : "";
  do {
    await sleep(config.bubble.dataApiSleepMs);
    const url = `${endpoint}?cursor=${offset}${constraints}`;
    const res = await fetchBubble(url, "GET", token);
    const { cursor, results, remaining: newRemaining } = res.response;
    remaining = newRemaining;
    objList = [
      ...objList,
      ...results
    ];
    offset += results.length;
  }while (remaining > 0)
  return objList;
}












async function createMany(baseUrl, token, type, objList) {
  const url = `${baseUrl}${type}/bulk`;
  const data = objList.map((obj)=>JSON.stringify(obj)).join("\n");
  try {
    await sleep(config.bubble.dataApiSleepMs);
    const res = await fetchBubble(url, "POST", token, data);
    return res.map((obj)=>obj.status === "success" ? obj.id : null).filter((id)=>id !== null);
  } catch (err) {
    console.error(`Error in createMany: ${err}`);
    return [];
  }
}










async function updateOne(baseUrl, token, type, objectId, data) {
  const url = `${baseUrl}${type}/${objectId}`;
  const body = JSON.stringify(data);
  try {
    await sleep(config.bubble.dataApiSleepMs);
    await fetchBubble(url, "PATCH", token, body);
  } catch (err) {
    console.error(`Error in updateOne: ${err}`);
    console.error(err);
  }
}
const whitelistedLocodes = [
  "SEGOT",
  "PECLL",
  "FRBOL",
  "CAVAN",
  "AEFJR",
  "GRKLL",
  "SEHLD",
  "BEZEE",
  "NLVLI",
  "NOTOS",
  "SESDL",
  "GBSOU",
  "NLRTM",
  "DERSK",
  "ISREY",
  "ISRFJ",
  "GBPTL",
  "FIRAU",
  "FIPOR",
  "SESTO",
  "SESOE",
  "SENYN",
  "SEOXE",
  "SENRK",
  "DETRV",
  "DELBC",
  "FRLRT",
  "SJLYR",
  "LVRIX",
  "FRLEH",
  "DEKEL",
  "SEKLR",
  "SEOSK",
  "LVVNT",
  "NOKKN",
  "NOBJF",
  "FIPRV",
  "NOHVG",
  "NOHFT",
  "DEHAM",
  "GBGSY",
  "SEKAN",
  "SEHAD",
  "DKHIR",
  "SEVST",
  "SEGVX",
  "FOTHO",
  "FOFUG",
  "GBFAL",
  "DEEME",
  "PLSZZ",
  "PLSWI",
  "DECKL",
  "DECUX",
  "DEWVN",
  "DEBRE",
  "NOBGO",
  "GBGLA",
  "GBBEL",
  "PLKOL",
  "LVLPX",
  "PLDAR",
  "LTKLJ",
  "PLGDN",
  "PLHEL",
  "PLGDY",
  "RUBLT",
  "RUKGD",
  "RUMMK",
  "RUARH",
  "BEANR",
  "NLIJM",
  "NLAMS",
  "GBABD",
  "MUPLU",
  "GAPOG",
  "CGPNR",
  "AOLAD",
  "ILHFA",
  "MZMPM",
  "ZARCB",
  "ZADUR",
  "FIHEL",
  "EEMUG",
  "EETLL",
  "EEPLA",
  "CVMIN",
  "SNDKR",
  "MACAS",
  "ZAPLZ",
  "KWKWI",
  "IRBIK",
  "AEJEA",
  "AEDXB",
  "IRBND",
  "SADMM",
  "BHBAH",
  "ILASH",
  "DZALG",
  "EGALY",
  "JOAQJ",
  "EGPSD",
  "EGSUZ",
  "EGAIS",
  "SAJED",
  "SDPZU",
  "YEADE",
  "NGLOS",
  "TGLFW",
  "BJCOO",
  "GHTEM",
  "GHTKD",
  "CIABJ",
  "KRYOS",
  "JPTYO",
  "CNTSN",
  "AUSYD",
  "IDSUB",
  "RULED",
  "FIKTK",
  "RUULU",
  "RUPRI",
  "RUSOV",
  "RUVYS",
  "SGSIN",
  "CNTAO",
  "MYPKG",
  "RUPKC",
  "MYPEN",
  "PFPPT",
  "JPOSA",
  "FJSUV",
  "NCNOU",
  "CNSHA",
  "CNZOS",
  "CNNGB",
  "AUNTL",
  "INBOM",
  "PHMNL",
  "RUZAR",
  "RUVVO",
  "RUNJK",
  "RUKOZ",
  "RUUGL",
  "RUKHO",
  "RUKOR",
  "IDJKT",
  "KRINC",
  "TWKHH",
  "TWKEL",
  "TWTXG",
  "TWSUO",
  "TWHUN",
  "HKHKG",
  "VNSGN",
  "VNHPH",
  "CNCAN",
  "AUMEL",
  "AUGEX",
  "AUKWI",
  "AUFRE",
  "AUDRW",
  "AUGET",
  "CNDLC",
  "LKCMB",
  "LKGAL",
  "BDCGP",
  "LKTRR",
  "INMAA",
  "PHCEB",
  "PGPOM",
  "AUTSV",
  "AUCNS",
  "KRUSN",
  "KRPUS",
  "AUDAM",
  "AUBME",
  "AUGLT",
  "AUBNE",
  "INIXY",
  "INMUN",
  "PKKHI",
  "PKBQM",
  "THKSI",
  "THBKK",
  "IDBPN",
  "NZWLG",
  "NZTRG",
  "NZWRE",
  "NZAKL",
  "BQEUX",
  "PRSJU",
  "CRLIO",
  "PAPCN",
  "JMKIN",
  "BBBGI",
  "MXPVR",
  "MXTPB",
  "USSEA",
  "USSFO",
  "CAQUE",
  "USPWM",
  "MXPPE",
  "USPHL",
  "USORF",
  "USNYC",
  "USMSY",
  "USMOB",
  "BSFPO",
  "USMIA",
  "MXZLO",
  "USLAX",
  "USLGB",
  "USTPA",
  "USJAX",
  "CAHAL",
  "USHOU",
  "USCRP",
  "USILM",
  "USSAV",
  "USCHS",
  "SEPIT",
  "SELLA",
  "CAMTR",
  "DKNBG",
  "FITKU",
  "FRIRK",
  "FRDKK",
  "SEMMA",
  "DKCPH",
  "SEHEL",
  "TTPOS",
  "AWAUA",
  "CWCUR",
  "BQBON",
  "MXATM",
  "MXTAM",
  "MXTUX",
  "MXCOA",
  "MXVER",
  "BRRIO",
  "ARSLO",
  "BRRIG",
  "CLPCH",
  "CLPUQ",
  "ARCVI",
  "ARUSH",
  "FKPSY",
  "CLCNL",
  "CLTAL",
  "CLLQN",
  "CLSAI",
  "CLVAP",
  "CLQTV",
  "BRPNG",
  "SRPBM",
  "ARMDQ",
  "BRMAO",
  "BRSSA",
  "BRSTS",
  "BRMCZ",
  "BRSUA",
  "BRREC",
  "BRFOR",
  "ECPBO",
  "ECLLD",
  "ECGYE",
  "ECMEC",
  "ECESM",
  "COCTG",
  "ARROS",
  "ARSNS",
  "UYMVD",
  "ARZAE",
  "ARBUE",
  "BRITQ",
  "BRVDC",
  "BRBEL",
  "BOTDD",
  "CLPTC",
  "CLHSO",
  "CLARI",
  "CLTOQ",
  "CLIQQ",
  "CLPTI",
  "CLMJS",
  "CLANF",
  "HRVUK",
  "ESVGO",
  "ITVCE",
  "ESVLC",
  "ITTAR",
  "GRJSY",
  "GRPIR",
  "ITNAP",
  "MTMLA",
  "BGVID",
  "BGLOM",
  "PTSIE",
  "PTLIS",
  "CYLMS",
  "CYLCA",
  "ESSCT",
  "ESLPA",
  "ITLIV",
  "HRRJK",
  "ITTRS",
  "SIKOP",
  "UAODS",
  "TRIZM",
  "BRVIX",
  "BRTUB",
  "BRFNO",
  "NAWVB",
  "ZACPT",
  "TRIST",
  "ITSPE",
  "ITGOA",
  "FRMRS",
  "FRFOS",
  "ROGAL",
  "ROCND",
  "BGVAR",
  "BGVAZ",
  "BGBOJ",
  "ESBCN",
  "GEPTI",
  "RUASF",
  "GEBUS",
  "AZBAK",
  "GEKUL",
  "UASVP",
  "UAKHE",
  "GESUI",
  "RUTAM",
  "RUTUA",
  "RUNVS",
  "RURND",
  "RUTAG",
  "RUAZO",
  "ITAUG",
  "ITRAN",
  "ITAOI",
  "MATNG",
  "ESCEU",
  "GIGIB",
  "ESALG",
  "ESMPG",
  "ESLCG"
];
