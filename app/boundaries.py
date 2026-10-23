"""Small, editable GeoJSON field polygons (longitude, latitude order)."""
import math
from typing import Literal
from pydantic import BaseModel, Field, model_validator


def cross(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def intersects(a,b,c,d):
    def on(a,b,p):
        return abs(cross(a,b,p))<1e-12 and min(a[0],b[0])-1e-12<=p[0]<=max(a[0],b[0])+1e-12 and min(a[1],b[1])-1e-12<=p[1]<=max(a[1],b[1])+1e-12
    return (cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0) or any((on(a,b,c),on(a,b,d),on(c,d,a),on(c,d,b)))


class Boundary(BaseModel):
    type: Literal['Polygon']='Polygon'
    coordinates: list[list[list[float]]] = Field(min_length=1,max_length=1)

    @model_validator(mode='after')
    def valid_polygon(self):
        ring=self.coordinates[0]
        if not 4<=len(ring)<=201 or ring[0]!=ring[-1]:
            raise ValueError('Контур: 3–200 вершин із замкненою межею.')
        for point in ring:
            if len(point)!=2 or not all(math.isfinite(x) for x in point) or not -180<=point[0]<=180 or not -90<=point[1]<=90:
                raise ValueError('Некоректні координати вершини.')
        points=ring[:-1]
        if len({tuple(p) for p in points})!=len(points):raise ValueError('Вершини не мають повторюватися.')
        if max(p[0] for p in points)-min(p[0] for p in points)>180:raise ValueError('Контур не може перетинати лінію зміни дат.')
        # Translate before area calculation to avoid cancellation at high precision.
        area=sum(cross(points[0],ring[i],ring[i+1]) for i in range(1,len(points)))
        if abs(area)<1e-12:raise ValueError('Контур має охоплювати ділянку, а не пряму лінію.')
        n=len(points)
        for i in range(n):
            for j in range(i+1,n):
                if j==i+1 or (i==0 and j==n-1):continue
                if intersects(ring[i],ring[i+1],ring[j],ring[j+1]):raise ValueError('Межі поля не мають перетинатися.')
        return self

    def weather_point(self):
        """Midpoint of an interior scanline segment, including concave polygons."""
        ring=self.coordinates[0]
        levels=sorted({p[1] for p in ring})
        y=(levels[len(levels)//2-1]+levels[len(levels)//2])/2
        xs=[]
        for a,b in zip(ring,ring[1:]):
            if (a[1]>y)!=(b[1]>y):xs.append(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
        xs.sort()
        left,right=max(zip(xs[::2],xs[1::2]),key=lambda pair:pair[1]-pair[0])
        return {'latitude':y,'longitude':(left+right)/2}
