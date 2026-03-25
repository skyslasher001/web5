import { Check } from 'lucide-react';

const services = [
  {
    name: 'Essential',
    price: '$2,500',
    duration: 'Starting at',
    image:
      'https://images.pexels.com/photos/3735218/pexels-photo-3735218.jpeg?auto=compress&cs=tinysrgb&w=600',
    features: [
      'Custom responsive design',
      'Up to 5 pages',
      'SEO optimization',
      'Mobile-first approach',
      '30 days support',
    ],
  },
  {
    name: 'Professional',
    price: '$5,000',
    duration: 'Starting at',
    image:
      'https://images.pexels.com/photos/1090972/pexels-photo-1090972.jpeg?auto=compress&cs=tinysrgb&w=600',
    features: [
      'Everything in Essential',
      'Up to 15 pages',
      'CMS integration',
      'Advanced animations',
      'Performance optimization',
      '90 days support',
    ],
    popular: true,
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    duration: 'Tailored solution',
    image:
      'https://images.pexels.com/photos/3184292/pexels-photo-3184292.jpeg?auto=compress&cs=tinysrgb&w=600',
    features: [
      'Everything in Professional',
      'Unlimited pages',
      'Custom functionality',
      'Dedicated support team',
      'Priority updates',
      'Ongoing maintenance',
    ],
  },
];

export default function Services() {
  return (
    <section id="services" className="py-24 bg-white">
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-5xl md:text-6xl font-serif text-gray-900 mb-4">
            Services We Offer
          </h2>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Choose the perfect package to elevate your digital presence
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-8">
          {services.map((service, index) => (
            <div
              key={index}
              className={`relative group bg-white rounded-2xl overflow-hidden shadow-lg hover:shadow-2xl transition-all duration-500 hover:-translate-y-2 ${
                service.popular ? 'ring-2 ring-emerald-600' : ''
              }`}
            >
              {service.popular && (
                <div className="absolute top-4 right-4 bg-emerald-600 text-white px-4 py-1 rounded-full text-sm font-medium z-10">
                  Popular
                </div>
              )}

              <div className="aspect-[4/3] overflow-hidden">
                <img
                  src={service.image}
                  alt={service.name}
                  className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700"
                />
              </div>

              <div className="p-8">
                <h3 className="text-2xl font-serif text-gray-900 mb-2">
                  {service.name}
                </h3>
                <div className="mb-6">
                  <span className="text-sm text-gray-500">{service.duration}</span>
                  <div className="text-4xl font-bold text-gray-900 mt-1">
                    {service.price}
                  </div>
                </div>

                <ul className="space-y-3 mb-8">
                  {service.features.map((feature, idx) => (
                    <li key={idx} className="flex items-start gap-3">
                      <Check
                        size={20}
                        className="text-emerald-600 flex-shrink-0 mt-0.5"
                      />
                      <span className="text-gray-600">{feature}</span>
                    </li>
                  ))}
                </ul>

                <a
                  href="#contact"
                  className={`block w-full text-center py-3 rounded-full font-medium transition-all duration-300 ${
                    service.popular
                      ? 'bg-emerald-600 text-white hover:bg-emerald-700 hover:shadow-lg'
                      : 'bg-gray-100 text-gray-900 hover:bg-gray-200'
                  }`}
                >
                  Get Started
                </a>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
