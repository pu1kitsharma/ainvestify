export const mandateTypes = [
 {value: 'fundraising_advisory', label: 'Fundraising advisory', hint: 'We help the company raise from institutional investors.'},
 {value: 'incubation', label: 'Incubation', hint: 'We build the company toward investment readiness.'},
 {value: 'sell_side_advisory', label: 'Sell-side advisory', hint: 'We advise on a sale or strategic transaction.'},
];
export const mandateLabel = (value?: string | null) => mandateTypes.find(item => item.value === value)?.label ?? value ?? '';
