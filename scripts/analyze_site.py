"""Point-based regional climate context, never a field soil diagnosis."""
import json
import calendar
from datetime import datetime, timezone
import requests
from app import config

LAT, LON = 49.857746039603526, 29.469316542565025
OUT = config.DATA / 'site'


def summarize(payload):
    values = payload['properties']['parameter']
    missing = payload.get('header',{}).get('fill_value',-999)
    result=[]
    for year in range(2016,2026):
        dates=sorted(d for d in values['T2M'] if d.startswith(str(year)))
        expected=366 if calendar.isleap(year) else 365
        if len(dates)!=expected or any(values[k].get(d,missing)==missing for k in values for d in dates):
            raise ValueError(f'Incomplete data for {year}')
        spring=[d for d in dates if '0301'<=d[4:]<='0630' and values['T2M_MIN'][d]<0]
        autumn=[d for d in dates if '0801'<=d[4:]<='1130' and values['T2M_MIN'][d]<0]
        result.append({'year':year,'mean_temperature_c':round(sum(values['T2M'][d] for d in dates)/len(dates),1),
            'precipitation_mm':round(sum(values['PRECTOTCORR'][d] for d in dates),1),
            'april_september_rain_mm':round(sum(values['PRECTOTCORR'][d] for d in dates if '0401'<=d[4:]<='0930'),1),
            'days_tmax_ge30':sum(values['T2M_MAX'][d]>=30 for d in dates),
            'last_spring_tmin_below_zero':max(spring) if spring else None,
            'first_autumn_tmin_below_zero':min(autumn) if autumn else None})
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    url='https://power.larc.nasa.gov/api/temporal/daily/point'
    params={'parameters':'T2M,T2M_MIN,T2M_MAX,PRECTOTCORR','community':'AG','latitude':LAT,'longitude':LON,
            'start':'20160101','end':'20251231','format':'JSON','time-standard':'UTC'}
    response=requests.get(url,params=params,timeout=(15,120));response.raise_for_status()
    payload=response.json(); (OUT/'nasa_power_2016_2025.json').write_text(json.dumps(payload))
    annual=summarize(payload)
    result={'point':{'latitude':LAT,'longitude':LON},'source':'NASA POWER', 'source_url':response.url,
            'retrieved_at':datetime.now(timezone.utc).isoformat(),'annual':annual,
            'mean_annual_rain_mm':round(sum(x['precipitation_mm'] for x in annual)/len(annual)),
            'mean_april_september_rain_mm':round(sum(x['april_september_rain_mm'] for x in annual)/len(annual)),
            'mean_temperature_c':round(sum(x['mean_temperature_c'] for x in annual)/len(annual),1),
            'limitations':'Regional gridded model data for 2016–2025, not a 30-year climate normal or measurements on this field. Air frost proxy is not soil frost. No boundary, area, soil chemistry or exact sowing dates inferred.'}
    try:
        elevation=requests.get('https://api.open-meteo.com/v1/elevation',params={'latitude':LAT,'longitude':LON},timeout=20)
        elevation.raise_for_status();result['elevation_m']=elevation.json()['elevation'][0]
        result['elevation_source']='Copernicus DEM GLO-90 via Open-Meteo, 90 m grid'
    except requests.RequestException:
        result['elevation_m']=None
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
