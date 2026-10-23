"""Validated user-owned points and bounded settlement lookup."""
import math
import os
import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

router=APIRouter()


class Coordinates(BaseModel):
    latitude: float | None = Field(default=None,ge=-90,le=90,allow_inf_nan=False)
    longitude: float | None = Field(default=None,ge=-180,le=180,allow_inf_nan=False)

    @model_validator(mode='after')
    def paired(self):
        if (self.latitude is None)!=(self.longitude is None):
            raise ValueError('Вкажіть обидві координати або залиште обидві порожніми.')
        return self


class Location(Coordinates):
    location_name: str = Field(default='',max_length=300)


@router.get('/api/farm/location')
def read_location():
    from app import farm
    return farm.location()


@router.put('/api/farm/location')
def update_location(value:Location):
    from app import farm
    return farm.save_location(value)


@router.get('/api/locations/search')
def search(q:str=Query(min_length=2,max_length=150)):
    query=q.strip()
    if len(query)<2:raise HTTPException(422,'Введіть щонайменше два символи.')
    key=os.getenv('OPEN_METEO_API_KEY')
    url='https://customer-geocoding-api.open-meteo.com/v1/search' if key else 'https://geocoding-api.open-meteo.com/v1/search'
    params={'name':query,'count':8,'language':'uk','format':'json'}
    if key:params['apikey']=key
    try:
        response=requests.get(url,params=params,timeout=(3,7))
        response.raise_for_status()
        raw=response.json()
        results=[]
        for row in raw.get('results',[])[:8]:
            lat=row.get('latitude');lon=row.get('longitude')
            if not isinstance(lat,(float,int)) or not isinstance(lon,(float,int)):continue
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:continue
            label=', '.join(str(row[k]) for k in ('name','admin1','country') if row.get(k))[:300]
            if label:results.append({'latitude':lat,'longitude':lon,'location_name':label})
        return {'results':results,'source':'Open-Meteo / GeoNames','source_url':'https://open-meteo.com/en/docs/geocoding-api'}
    except (requests.RequestException,ValueError,KeyError,TypeError,AttributeError):
        raise HTTPException(503,'Пошук населених пунктів тимчасово недоступний. Можна ввести координати вручну.') from None
