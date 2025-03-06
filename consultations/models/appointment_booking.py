from odoo import api, fields, models, _
from datetime import datetime

class AppointmentBooking(models.Model):
    _name = "appointment.booking"
    _description = "Appointment Booking"

    patient_id = fields.Many2one(
        'res.partner', 
        string="Patient", 
        required=True, 
        help="Select existing patient or create a new one."
    )
    name = fields.Char(string="Patient Name", required=True)
    reference_id = fields.Char(string="Patient Reference ID", readonly=True, copy=False)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('others', 'Others')
    ])
    date_of_birth = fields.Date(string="Date of Birth")
    age = fields.Integer(string="Age", compute='_compute_age', store=True)
    phone = fields.Char(string="Phone")
    email = fields.Char(string="Email")
    appointment_date = fields.Date(string="Appointment Date", required=True)
    op_number = fields.Char(string="OP Number", readonly=True, copy=False, default=lambda self: _('New'))
    
    department = fields.Selection([
        ('kayachikitsa', 'KAYACHIKITSA'),
        ('panchakarma', 'PANCHAKARMA'),
        ('streerogam_prasutitantra', 'STREEROGAM & PRASUTITANTRA'),
        ('kaumarabrityam', 'KAUMARABRITYAM'),
        ('shalyam', 'SHALAYAM'),
        ('shalakyam', 'SHALAKYAM'),
        ('swastavrittan', 'SWASTAVRITTAN'),
        ('emergency', 'EMERGENCY'),
        ('ip', 'IP'),
        ('counter_sales', 'COUNTER SALES')
    ], string="Department")

    consultation_doctor = fields.Many2one('consultation.doctor', string="Consultation Doctor")
    consultation_mode = fields.Selection([('online', 'Online'), ('offline', 'Offline')])
    if_online = fields.Text(string="If Online")
    referral = fields.Char(string="Referral(if Any)")
    priority = fields.Char(string="Priority")
    notes = fields.Text(string="Any Notes")

    patient_type = fields.Selection([
        ('new', 'New Patient'),
        ('old', 'Old Patient')
    ], string="Patient Type", compute="_compute_patient_type", store=True)

    state = fields.Selection([
        ('booked', 'Appointment Booked'),
        ('completed', 'Consultation Completed'),
        ('cancelled', 'Cancelled')
    ], string="Status", default='booked', tracking=True, required=True)

    doctor_appointment_id = fields.Many2one(
        'doctor.appointments',
        string="Doctor Appointment",
        readonly=True,
        help="Automatically linked Doctor Appointment"
    )

    @api.depends('date_of_birth')
    def _compute_age(self):
        """Calculate age from date_of_birth."""
        for record in self:
            if record.date_of_birth:
                today = datetime.today()
                birth_date = fields.Date.from_string(record.date_of_birth)
                record.age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            else:
                record.age = 0

    @api.depends('patient_id')
    def _compute_patient_type(self):
        """Determine if the patient is new or old."""
        for record in self:
            if record.patient_id:
                previous_appointments = self.env['appointment.booking'].search_count([
                    ('patient_id', '=', record.patient_id.id),
                    ('id', '!=', record.id)
                ])
                record.patient_type = 'old' if previous_appointments > 0 else 'new'
            else:
                record.patient_type = 'new'

    @api.onchange('patient_id')
    def _onchange_patient_id(self):
        """Auto-fill patient details and assign a reference ID if it does not exist."""
        if self.patient_id:
            self.name = self.patient_id.name
            self.phone = self.patient_id.phone
            self.email = self.patient_id.email
            
            # Fetch existing reference ID if patient already has one
            existing_ref_id = self.env['appointment.booking'].search([
                ('patient_id', '=', self.patient_id.id)
            ], limit=1).reference_id

            if existing_ref_id:
                self.reference_id = existing_ref_id
            else:
                self.reference_id = self._generate_reference_id(self.patient_id.id)

            self._compute_patient_type()

    def _generate_reference_id(self, patient_id):
        """Generate a unique reference ID for a patient."""
        return f'EHH-{patient_id:06d}'

    @api.model
    def create(self, vals):
        """Ensure Reference ID is auto-generated if it does not exist and sync with taf.bookings."""
        if vals.get('patient_id'):
            existing_ref_id = self.env['appointment.booking'].search([
                ('patient_id', '=', vals['patient_id'])
            ], limit=1).reference_id

            if existing_ref_id:
                vals['reference_id'] = existing_ref_id
            else:
                vals['reference_id'] = self._generate_reference_id(vals['patient_id'])

        if vals.get('op_number', 'New') == 'New':
            vals['op_number'] = self.env['ir.sequence'].next_by_code('appointment.op_number') or '0000'

        if vals.get('patient_id'):
            patient = self.env['res.partner'].browse(vals['patient_id'])
            vals['name'] = patient.name

        booking = super(AppointmentBooking, self).create(vals)

        doctor_appointment = self.env['doctor.appointments'].create({
            'booking_id': booking.id,
            'patient_id': booking.patient_id.id,
            'appointment_date': booking.appointment_date,
            'reference_id': booking.reference_id,
            'state': booking.state,
        })

        booking.doctor_appointment_id = doctor_appointment.id
        return booking

    def action_cancel(self):
        """Cancel an appointment."""
        self.write({'state': 'cancelled'})
        if self.doctor_appointment_id:
            self.doctor_appointment_id.write({'state': 'cancelled'})

    @api.model
    def sync_taf_bookings(self):
        """Sync new records from taf.bookings into appointment.booking automatically."""
        taf_bookings = self.env['taf.bookings'].search([])
        for taf in taf_bookings:
            existing_appointment = self.env['appointment.booking'].search([
                ('reference_id', '=', f'TAF-{taf.user_id.id}')
            ], limit=1)

            if not existing_appointment:
                self.create({
                    'name': taf.patient_name,
                    'email': taf.email,
                    'phone': taf.phone,
                    'appointment_date': taf.booking_date or fields.Date.today(),
                    'patient_id': taf.user_id.id,
                    'state': 'booked',
                    'reference_id': f'TAF-{taf.user_id.id}',
                })
                _logger.info("✅ Synced taf.bookings record to appointment.booking for: %s", taf.patient_name)