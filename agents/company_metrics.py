"""Dated company-reported figures and reproducible operating calculations.

No estimates, annualization, currency conversion or readiness scores. Notes retain
where supplied figures came from; saving an update does not verify it.
"""
from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

KEYS = {'revenue':'Recognized revenue','direct_costs':'Direct variable delivery costs','cash':'Cash at month end',
        'net_burn':'Net operating cash burn','paying_customers':'Paying customers','orders':'Completed orders','gmv':'Gross merchandise value'}

class MonthlyUpdate(BaseModel):
    month: str = Field(pattern=r'^20\d{2}-(0[1-9]|1[0-2])$')
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    source_note: str = Field(min_length=12,max_length=1000)
    revenue: Optional[Decimal] = Field(default=None,ge=0,allow_inf_nan=False,max_digits=18,decimal_places=4)
    direct_costs: Optional[Decimal] = Field(default=None,ge=0,allow_inf_nan=False,max_digits=18,decimal_places=4)
    cash: Optional[Decimal] = Field(default=None,ge=0,allow_inf_nan=False,max_digits=18,decimal_places=4)
    net_burn: Optional[Decimal] = Field(default=None,allow_inf_nan=False,max_digits=18,decimal_places=4)
    paying_customers: Optional[int] = Field(default=None,ge=0,strict=True)
    orders: Optional[int] = Field(default=None,ge=0,strict=True)
    gmv: Optional[Decimal] = Field(default=None,ge=0,allow_inf_nan=False,max_digits=18,decimal_places=4)

    @field_validator('revenue','direct_costs','cash','net_burn','gmv',mode='before')
    @classmethod
    def reject_boolean(cls,value):
        if isinstance(value,bool): raise ValueError('A financial figure cannot be a boolean')
        return value

    @model_validator(mode='after')
    def historical(self):
        if self.month >= date.today().strftime('%Y-%m'):
            raise ValueError('Use a completed historical month; forecasts and partial months must not be mixed with actuals')
        if not any(getattr(self,k) is not None for k in KEYS):
            raise ValueError('Supply at least one figure; leave unavailable fields blank')
        return self


def metrics_report(updates):
    latest = {}
    for update in updates:
        latest[update['month']] = update
    rows = [latest[k] for k in sorted(latest)]
    calculations = []
    def value(row,key):
        return Decimal(str(row[key])) if row.get(key) is not None else None
    def add(name,number,unit,formula,inputs,explanation):
        calculations.append(dict(name=name,value=str(round(number,2)),unit=unit,formula=formula,inputs=inputs,explanation=explanation,status='calculated_from_company_reported_figures'))
    if rows:
        now = rows[-1]; rev=value(now,'revenue'); costs=value(now,'direct_costs')
        if rev is not None and costs is not None:
            add('Delivery contribution',rev-costs,now['currency'],'revenue - direct_costs',[now['id']], 'Recognized revenue less supplied direct variable costs. Excludes overhead and taxes; not total company profit.')
            if rev>0:
                add('Delivery contribution margin',(rev-costs)/rev*100,'%', '(revenue - direct_costs) / revenue × 100',[now['id']], 'Only meaningful if the revenue and direct-cost treatment are consistent.')
        cash=value(now,'cash'); burn=value(now,'net_burn')
        if cash is not None and burn is not None and burn>0:
            add('Cash coverage',cash/burn,'months','cash / net_burn',[now['id']], 'Assumes constant net operating burn. Exclude financing flows and restricted cash; this is not a forecast.')
        gmv=value(now,'gmv'); orders=value(now,'orders')
        if gmv is not None and orders is not None and orders>0:
            add('Average completed order value',gmv/orders,now['currency'],'gmv / orders',[now['id']], 'Requires GMV for these completed orders. Order value is not company revenue.')
        if len(rows)>1:
            prev=rows[-2]
            month_number=lambda r:int(r['month'][:4])*12+int(r['month'][5:])
            prior=value(prev,'revenue')
            if month_number(now)-month_number(prev)==1 and now['currency']==prev['currency'] and rev is not None and prior is not None and prior>0:
                add('Revenue change from prior month',(rev/prior-1)*100,'%', '(current revenue / prior revenue - 1) × 100',[prev['id'],now['id']], 'Consecutive full months, same currency and recognized-revenue definition. Not annual growth or proof of a durable trend.')
    return dict(months=rows,calculations=calculations,latest_month=rows[-1]['month'] if rows else None,
                missing=[KEYS[k] for k in KEYS if not rows or rows[-1].get(k) is None],
                note='Company-reported figures, not independently verified. Blank means unknown, not zero.')
