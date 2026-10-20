import {mount} from '/runtime/runtime.js';

const fields = ['name', 'email_id', 'phone_number', 'upi_id'];

mount({
  defaults: {name: '', email_id: '', phone_number: '', upi_id: ''},
  collect() {
    return Object.fromEntries(fields.map(name => [name, document.getElementById(name).value]));
  },
  render(data) {
    for (const name of fields) {
      if (typeof data[name] !== 'string') throw new Error(`${name} must be text`);
      document.getElementById(name).value = data[name];
    }
  },
  validate(data) {
    const errors = [];
    if (!data.name.trim()) errors.push({field: 'name', message: 'Enter your name.'});
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email_id)) errors.push({field: 'email_id', message: 'Enter a valid email address.'});
    const digits = data.phone_number.replace(/\D/g, '');
    if (!/^\+?[\d\s().-]+$/.test(data.phone_number) || digits.length < 7 || digits.length > 15) errors.push({field: 'phone_number', message: 'Enter a valid phone number (7–15 digits).'});
    if (data.upi_id && !/^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$/.test(data.upi_id)) errors.push({field: 'upi_id', message: 'Enter a UPI ID such as name@bank, or leave it empty.'});
    return errors;
  }
});
